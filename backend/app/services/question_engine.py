"""Deterministic natural-language question planning and calculation.

The engine interprets common analytical questions and computes answers with
pandas. The LLM only receives these calculated facts for explanation; it is
never asked to perform arithmetic or generate SQL/Python.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.utils.data_validation import (
    categorical_columns,
    datetime_columns,
    numeric_columns,
)
from app.utils.serialization import json_safe

_SUMMARY_WORDS = ("summarize", "summary", "overview", "management", "executive", "describe")
_CORRELATION_WORDS = ("correlation", "correlate", "relationship between", "related")
_TREND_WORDS = ("trend", "over time", "monthly", "growth", "seasonal", "time series")
_ANOMALY_WORDS = ("unusual", "anomaly", "anomalies", "outlier", "outliers", "abnormal", "strange")
_COUNT_WORDS = ("how many", "count of", "number of")
_DIRECTION_HIGH = ("highest", "largest", "maximum", "max", "top", "most", "best", "strongest")
_DIRECTION_LOW = ("lowest", "smallest", "minimum", "min", "least", "worst", "weakest")
_METRIC_PREFERENCE = ("revenue", "sales", "amount", "total", "spend", "value", "price", "quantity")
_ALIASES = {
    "sales": ("revenue", "total_sales", "sales_amount"),
    "revenue": ("revenue", "sales", "amount"),
    "profit": ("profit", "margin", "revenue"),
    "cost": ("cost", "spend", "expense"),
    "price": ("unit_price", "price"),
    "customers": ("customer_id", "customer"),
    "transactions": ("transaction_id",),
    "clicks": ("clicks",),
    "impressions": ("impressions",),
}


@dataclass
class QuestionResult:
    """Result of a deterministic question analysis."""

    question_type: str
    answer: str = ""
    facts: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    columns_used: list[str] = field(default_factory=list)
    table: list[dict[str, Any]] = field(default_factory=list)

    def fact(self, label: str, value: Any, method: str) -> None:
        self.facts.append({"label": label, "value": json_safe(value), "method": method})


def _fmt(value: Any, decimals: int = 2) -> str:
    """Format a numeric value for inclusion in a deterministic sentence."""
    safe = json_safe(value)
    if safe is None:
        return "n/a"
    if isinstance(safe, bool):
        return "yes" if safe else "no"
    if isinstance(safe, (int, float)):
        if abs(safe) >= 1000:
            return f"{safe:,.{decimals}f}"
        return f"{safe:,.{decimals}f}".rstrip("0").rstrip(".")
    return str(safe)


class QuestionEngine:
    """Plans and answers dataset questions using only deterministic pandas logic."""

    def __init__(self, df: pd.DataFrame, profile: dict[str, Any] | None = None) -> None:
        self.df = df
        self.profile = profile or {}
        self.numeric_cols = numeric_columns(df)
        self.categorical_cols = categorical_columns(df)
        self.datetime_cols = datetime_columns(df)

    def answer(self, question: str) -> QuestionResult:
        text = question.lower().strip()
        if not text:
            return self._unknown("Please ask a question about this dataset.")
        if self.df.empty:
            return self._unknown(
                "The dataset contains no rows, so this question cannot be answered."
            )

        if any(word in text for word in _SUMMARY_WORDS):
            return self._summary(text)
        if any(word in text for word in _ANOMALY_WORDS):
            return self._outliers(text)
        if any(word in text for word in _CORRELATION_WORDS):
            return self._correlation(text)
        if any(word in text for word in _TREND_WORDS):
            return self._trend(text)
        if any(word in text for word in _COUNT_WORDS):
            return self._count(text)

        matched_cats = self._match_columns(text, self.categorical_cols, include_ids=False)
        matched_nums = self._match_columns(text, self.numeric_cols, include_ids=False)
        if not matched_nums and self._has_aggregate_intent(text):
            metric = self._resolve_metric([], text)
            if metric is not None:
                matched_nums = [(metric, 0)]
        wants_group = self._wants_group(text, matched_cats, matched_nums)

        if wants_group and matched_cats:
            return self._group_aggregate(text, matched_cats, matched_nums)
        if matched_nums:
            return self._scalar_aggregate(text, matched_nums)
        if matched_cats:
            return self._category_distribution(text, matched_cats)
        return self._unknown(
            "I could not match this question to a column in the dataset. "
            "Ask about a specific numeric column (for example an average or total) "
            "or a categorical column (for example its distribution)."
        )

    # --------------------------------------------------------------- matching

    def _match_columns(
        self, text: str, columns: list[str], include_ids: bool = True
    ) -> list[tuple[str, int]]:
        """Return (column, match position) pairs mentioned in the question."""
        matches: list[tuple[str, int]] = []
        for column in columns:
            if not include_ids and self._is_identifier(column):
                continue
            name = str(column).lower()
            variants = {name, name.replace("_", " "), name.replace(" ", "_")}
            for variant in variants:
                if not variant:
                    continue
                pattern = r"(?<![a-z0-9_])" + re.escape(variant) + r"(?:s)?(?![a-z0-9_])"
                match = re.search(pattern, text)
                if match:
                    matches.append((column, match.start()))
                    break
        return matches

    def _resolve_metric(self, candidates: list[tuple[str, int]], text: str) -> str | None:
        """Choose a metric column, applying aliases when no exact match exists."""
        if candidates:
            exact = [column for column, _ in candidates]
            for preferred in _METRIC_PREFERENCE:
                for column in exact:
                    if preferred in str(column).lower():
                        return column
            return exact[0]
        for alias, targets in _ALIASES.items():
            if alias in text:
                for target in targets:
                    for column in self.numeric_cols:
                        if str(column).lower() == target:
                            return column
        for preferred in _METRIC_PREFERENCE:
            for column in self.numeric_cols:
                if preferred in str(column).lower():
                    return column
        return self.numeric_cols[0] if len(self.numeric_cols) == 1 else None

    @staticmethod
    def _is_identifier(column: str) -> bool:
        name = str(column).lower()
        return name.endswith("_id") or name in {"id", "index", "uuid"}

    def _wants_group(
        self,
        text: str,
        matched_cats: list[tuple[str, int]],
        matched_nums: list[tuple[str, int]],
    ) -> bool:
        if not matched_cats:
            return False
        group_words = (" by ", " per ", " each ", " which ", " what ", " breakdown", " split")
        if any(word in f" {text} " for word in group_words):
            return True
        direction = _DIRECTION_HIGH + _DIRECTION_LOW
        return bool(matched_nums) and any(word in text for word in direction)

    # -------------------------------------------------------------- handlers

    def _scalar_aggregate(self, text: str, matched_nums: list[tuple[str, int]]) -> QuestionResult:
        metric = self._resolve_metric(matched_nums, text)
        if metric is None or metric not in self.df.columns:
            return self._unknown("I could not identify a numeric column to aggregate.")
        aggregation = self._detect_aggregation(text, default="mean")
        if aggregation in {"max", "min"}:
            aggregation = (
                "mean"
                if not any(word in text for word in ("maximum", "minimum", "highest", "lowest"))
                else aggregation
            )

        series = pd.to_numeric(self.df[metric], errors="coerce").dropna()
        if series.empty:
            return self._unknown(f"Column '{metric}' has no numeric values to analyze.")
        value = getattr(series, aggregation)()
        result = QuestionResult(
            question_type="aggregate",
            answer=(
                f"The {aggregation} of '{metric}' is {_fmt(value)} "
                f"across {len(series):,} non-missing record(s)."
            ),
            columns_used=[metric],
        )
        result.fact(f"{aggregation.title()} of {metric}", value, f"pandas Series.{aggregation}()")
        result.fact("Non-missing records", len(series), "count of non-null values")
        result.context = {
            "metric": str(metric),
            "aggregation": aggregation,
            "value": json_safe(value),
            "non_null_count": int(len(series)),
            "minimum": json_safe(series.min()),
            "maximum": json_safe(series.max()),
            "median": json_safe(series.median()),
        }
        return result

    def _group_aggregate(
        self,
        text: str,
        matched_cats: list[tuple[str, int]],
        matched_nums: list[tuple[str, int]],
    ) -> QuestionResult:
        group_column = self._choose_group_column(text, matched_cats)
        metric = self._resolve_metric(matched_nums, text)
        if metric is None:
            aggregation = "count"
        else:
            aggregation = self._detect_aggregation(text, default="sum")
            if aggregation in {"max", "min"}:
                aggregation = "sum"
            if aggregation not in {"sum", "mean", "median", "count"}:
                aggregation = "sum"

        if metric is None:
            grouped = self.df[group_column].value_counts(dropna=True).head(10)
            table = [
                {group_column: json_safe(index), "record_count": int(value)}
                for index, value in grouped.items()
            ]
            label = "record_count"
        else:
            series = pd.to_numeric(self.df[metric], errors="coerce")
            frame = pd.DataFrame({group_column: self.df[group_column], metric: series}).dropna()
            if frame.empty:
                return self._unknown(
                    f"No records have both a value in '{group_column}' and '{metric}'."
                )
            grouped = getattr(frame.groupby(group_column)[metric], aggregation)()
            grouped = grouped.sort_values(ascending=False)
            label = metric_label(metric, aggregation)
            table = [
                {group_column: json_safe(index), label: json_safe(value)}
                for index, value in grouped.head(10).items()
            ]

        if table:
            table = [{str(key): json_safe(value) for key, value in row.items()} for row in table]

        ascending = any(word in text for word in _DIRECTION_LOW)
        ranked = sorted(table, key=lambda row: row.get(label) or 0, reverse=not ascending)
        top = ranked[0] if ranked else None
        bottom = ranked[-1] if ranked else None
        result = QuestionResult(
            question_type="group_aggregate",
            columns_used=[group_column] + ([metric] if metric else []),
            table=ranked,
        )
        result.context = {
            "group_column": str(group_column),
            "metric": str(metric) if metric else None,
            "aggregation": aggregation,
            "group_count": len(table),
            "ranking": ranked,
            "direction": "ascending" if ascending else "descending",
        }
        if metric:
            result.fact("Grouped by", group_column, "categorical column")
            result.fact("Metric", metric, "numeric column")
            result.fact("Aggregation", aggregation, "pandas groupby")
        if top:
            top_value = top.get(label)
            result.fact(
                f"Top {group_column} by {label}",
                f"{top.get(group_column)} ({_fmt(top_value)})",
                "pandas groupby ranking",
            )
        if bottom and top and bottom.get(group_column) != top.get(group_column):
            result.fact(
                f"Lowest {group_column} by {label}",
                f"{bottom.get(group_column)} ({_fmt(bottom.get(label))})",
                "pandas groupby ranking",
            )
        result.fact("Groups analyzed", len(table), "number of groups returned")

        if top:
            direction_word = "lowest" if ascending else "highest"
            sentence = (
                f"By {label}, the {direction_word} {group_column} is "
                f"'{top.get(group_column)}' at {_fmt(top.get(label))}."
            )
            if not ascending and bottom and bottom.get(group_column) != top.get(group_column):
                sentence += (
                    f" The lowest is '{bottom.get(group_column)}' at {_fmt(bottom.get(label))}."
                )
            if metric:
                sentence += (
                    f" Values are the {aggregation} of '{metric}' across {len(table)} group(s)."
                )
            result.answer = sentence
        else:
            result.answer = "No groups were available to compare."
        return result

    def _choose_group_column(self, text: str, matched_cats: list[tuple[str, int]]) -> str:
        lowered = text
        by_match = re.search(r"\b(?:by|per)\s+([a-z_ ]{2,40})", lowered)
        if by_match:
            phrase = by_match.group(1)
            for column, _ in matched_cats:
                name = str(column).lower().replace("_", " ")
                if name in phrase:
                    return column
        noun_phrase = re.search(
            r"\b(?:which|what)\s+([a-z_ ]{2,60}?)\s+(?:has|have|had|contributes|shows|gets|receives|sells|generates)\b",
            lowered,
        )
        if noun_phrase:
            phrase = noun_phrase.group(1)
            candidates = [
                (column, position)
                for column, position in matched_cats
                if str(column).lower().replace("_", " ") in phrase
            ]
            if candidates:
                # The head noun is normally the last matched column in the phrase.
                return max(candidates, key=lambda item: item[1])[0]
        # Prefer a low-cardinality dimension over identifiers or free text.
        return min(
            matched_cats,
            key=lambda item: self.df[item[0]].nunique(dropna=True),
        )[0]

    def _category_distribution(
        self, text: str, matched_cats: list[tuple[str, int]]
    ) -> QuestionResult:
        column = self._choose_group_column(text, matched_cats)
        counts = self.df[column].value_counts(dropna=True)
        if counts.empty:
            return self._unknown(f"Column '{column}' has no values to summarize.")
        table = [
            {
                column: json_safe(index),
                "count": int(count),
                "percentage": round(float(count) / int(counts.sum()) * 100, 2),
            }
            for index, count in counts.head(10).items()
        ]
        result = QuestionResult(
            question_type="distribution",
            table=table,
            columns_used=[column],
            answer=(
                f"'{column}' has {int(counts.size):,} distinct value(s). The most common is "
                f"'{table[0][column]}' with {table[0]['count']:,} records "
                f"({table[0]['percentage']:.1f}%)."
            ),
            context={
                "column": str(column),
                "distribution": table,
                "unique_count": int(counts.size),
            },
        )
        result.fact(f"Distinct values in {column}", int(counts.size), "pandas nunique")
        result.fact(
            f"Most frequent {column}",
            f"{table[0][column]} ({table[0]['count']:,} records)",
            "pandas value_counts",
        )
        return result

    def _count(self, text: str) -> QuestionResult:
        matched = self._match_columns(text, self.df.columns.tolist())
        column = matched[0][0] if matched else None
        if column is None:
            for alias, targets in _ALIASES.items():
                if alias in text:
                    for target in targets:
                        for candidate in self.df.columns:
                            if str(candidate).lower() == target:
                                column = candidate
                                break
                    if column is not None:
                        break
        if "unique" in text and column is not None:
            value = int(self.df[column].nunique(dropna=True))
            answer = f"'{column}' has {value:,} distinct non-missing value(s)."
            method = "pandas Series.nunique()"
        else:
            value = int(len(self.df))
            column = None
            answer = f"The dataset contains {value:,} row(s)."
            method = "pandas DataFrame length"
        result = QuestionResult(
            question_type="count",
            answer=answer,
            columns_used=[column] if column else [],
            context={"count": value, "column": str(column) if column else None},
        )
        result.fact("Record count" if not column else f"Distinct {column}", value, method)
        return result

    def _correlation(self, text: str) -> QuestionResult:
        matched = [column for column, _ in self._match_columns(text, self.numeric_cols)]
        columns = matched if len(matched) >= 2 else self.numeric_cols[:8]
        if len(columns) < 2:
            return self._unknown(
                "At least two numeric columns are required to compute correlations."
            )
        correlations = self.df[columns].corr(numeric_only=True)
        pairs: list[dict[str, Any]] = []
        for i, first in enumerate(columns):
            for second in columns[i + 1 :]:
                value = correlations.loc[first, second]
                if pd.isna(value):
                    continue
                pairs.append(
                    {
                        "column_a": str(first),
                        "column_b": str(second),
                        "correlation": round(float(value), 4),
                        "strength": self._strength(float(value)),
                    }
                )
        pairs.sort(key=lambda item: abs(item["correlation"]), reverse=True)
        result = QuestionResult(
            question_type="correlation",
            columns_used=columns,
            context={"pairs": pairs[:8], "method": "Pearson correlation"},
            table=pairs[:8],
        )
        for pair in pairs[:5]:
            result.fact(
                f"Correlation: {pair['column_a']} vs {pair['column_b']}",
                f"{pair['correlation']:.3f} ({pair['strength']})",
                "pandas DataFrame.corr()",
            )
        if pairs:
            top = pairs[0]
            result.answer = (
                f"The strongest linear relationship is between '{top['column_a']}' and "
                f"'{top['column_b']}' with a Pearson correlation of {top['correlation']:.3f} "
                f"({top['strength']}). Correlation measures association, not causation, "
                f"and was computed on {len(self.df):,} rows."
            )
        else:
            result.answer = "No correlation could be computed from the available numeric columns."
        return result

    def _trend(self, text: str) -> QuestionResult:
        date_matches = self._match_columns(text, self.datetime_cols)
        date_column = (
            date_matches[0][0]
            if date_matches
            else (self.datetime_cols[0] if self.datetime_cols else None)
        )
        if date_column is None:
            return self._unknown(
                "No datetime column was detected, so a time trend cannot be calculated. "
                "Convert a date column to datetime in the cleaning step first."
            )
        num_matches = self._match_columns(text, self.numeric_cols)
        metric = self._resolve_metric(num_matches, text)
        dates = pd.to_datetime(self.df[date_column], errors="coerce")
        if dates.dropna().empty:
            return self._unknown(f"Column '{date_column}' contains no valid dates.")

        span_days = (dates.max() - dates.min()).total_seconds() / 86400
        frequency = "ME" if span_days > 60 else "D"
        period_format = "%Y-%m" if frequency == "ME" else "%Y-%m-%d"
        granularity_label = "month" if frequency == "ME" else "day"
        frame = pd.DataFrame({"date": dates})
        if metric:
            frame["value"] = pd.to_numeric(self.df[metric], errors="coerce")
            series = (
                frame.dropna(subset=["date"]).set_index("date")["value"].resample(frequency).sum()
            )
            aggregation = "sum"
            metric_label_value = metric
        else:
            series = frame.dropna(subset=["date"]).set_index("date").resample(frequency).size()
            aggregation = "count"
            metric_label_value = "record_count"
        series = series[series.index.notna()]
        if series.empty:
            return self._unknown("No time series values could be computed.")

        first, last = float(series.iloc[0]), float(series.iloc[-1])
        change = last - first
        change_pct = (change / abs(first) * 100) if first else None
        peak_period = series.idxmax()
        table = [
            {"period": index.strftime(period_format), "value": json_safe(value)}
            for index, value in series.items()
        ]
        result = QuestionResult(
            question_type="trend",
            columns_used=[date_column] + ([metric] if metric else []),
            table=table[-24:],
            context={
                "date_column": str(date_column),
                "metric": str(metric) if metric else None,
                "aggregation": aggregation,
                "frequency": granularity_label,
                "first_period": series.index[0].strftime(period_format),
                "first_value": json_safe(first),
                "last_period": series.index[-1].strftime(period_format),
                "last_value": json_safe(last),
                "change": json_safe(change),
                "change_percentage": json_safe(change_pct),
                "peak_period": peak_period.strftime(period_format),
                "peak_value": json_safe(series.max()),
            },
        )
        result.fact("Date column", date_column, "detected datetime column")
        result.fact("Metric", metric_label_value, f"resampled by {granularity_label}")
        result.fact(
            "First period value",
            f"{series.index[0].strftime(period_format)}: {_fmt(first)}",
            "pandas resample",
        )
        result.fact(
            "Latest period value",
            f"{series.index[-1].strftime(period_format)}: {_fmt(last)}",
            "pandas resample",
        )
        result.fact(
            "Change over period",
            f"{_fmt(change)}" + (f" ({change_pct:.1f}%)" if change_pct is not None else ""),
            "last minus first period",
        )
        result.fact(
            "Peak period",
            f"{peak_period.strftime(period_format)} ({_fmt(series.max())})",
            "pandas idxmax",
        )
        direction = "increased" if change > 0 else "decreased" if change < 0 else "remained flat"
        adverb = "monthly" if granularity_label == "month" else "daily"
        result.answer = (
            f"Between {series.index[0].strftime(period_format)} and "
            f"{series.index[-1].strftime(period_format)}, "
            f"the {adverb} {aggregation} of {metric_label_value} "
            f"{direction} from {_fmt(first)} to {_fmt(last)}"
            + (f" ({change_pct:+.1f}%)." if change_pct is not None else ".")
            + f" The peak period was {peak_period.strftime(period_format)} at {_fmt(series.max())}."
        )
        return result

    def _outliers(self, text: str) -> QuestionResult:
        candidates = self._match_columns(text, self.numeric_cols)
        columns = [column for column, _ in candidates] or self.numeric_cols
        if not columns:
            return self._unknown("No numeric columns are available for outlier analysis.")
        result = QuestionResult(question_type="outlier_scan", columns_used=columns)
        findings: list[dict[str, Any]] = []
        for column in columns[:8]:
            series = pd.to_numeric(self.df[column], errors="coerce").dropna()
            if series.empty:
                continue
            q1, q3 = series.quantile(0.25), series.quantile(0.75)
            iqr = q3 - q1
            if iqr <= 0:
                count = 0
                lower = upper = None
            else:
                lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                count = int(((series < lower) | (series > upper)).sum())
            findings.append(
                {
                    "column": str(column),
                    "outlier_count": count,
                    "percentage": round(count / len(series) * 100, 2),
                    "lower_bound": json_safe(lower),
                    "upper_bound": json_safe(upper),
                    "method": "IQR (1.5x)",
                }
            )
            result.fact(
                f"IQR outliers in {column}",
                f"{count:,} ({count / len(series) * 100:.1f}% of non-null values)",
                "IQR 1.5x rule",
            )
        findings.sort(key=lambda item: item["outlier_count"], reverse=True)
        result.context = {"findings": findings, "method": "IQR 1.5x rule"}
        result.table = findings
        if findings and findings[0]["outlier_count"]:
            top = findings[0]
            result.answer = (
                f"Using the IQR rule, '{top['column']}' contains the most unusual values: "
                f"{top['outlier_count']:,} record(s) ({top['percentage']:.1f}%). "
                "These are statistical outliers relative to the column distribution. "
                "For a multivariate view, run Isolation Forest anomaly detection; "
                "outliers are not necessarily errors or fraud."
            )
        else:
            result.answer = (
                "No IQR outliers were found in the numeric columns. "
                "Run Isolation Forest detection for a multivariate anomaly check."
            )
        return result

    def _summary(self, text: str) -> QuestionResult:
        profile = self.profile
        overview = profile.get("overview") or {}
        quality = profile.get("quality") or {}
        rows = int(overview.get("row_count", len(self.df)))
        columns = int(overview.get("column_count", self.df.shape[1]))
        missing_pct = overview.get("missing_percentage", 0)
        duplicates = overview.get("duplicate_rows", 0)
        result = QuestionResult(
            question_type="summary",
            answer=profile.get("summary")
            or (f"The dataset contains {rows:,} rows and {columns} columns."),
            columns_used=self.numeric_cols[:4] + self.categorical_cols[:2],
        )
        result.fact("Rows", rows, "DataFrame shape")
        result.fact("Columns", columns, "DataFrame shape")
        result.fact(
            "Column types",
            f"{len(self.numeric_cols)} numeric, {len(self.categorical_cols)} categorical, "
            f"{len(self.datetime_cols)} datetime",
            "pandas dtype inspection",
        )
        result.fact("Missing cells", f"{missing_pct}%", "pandas isna().sum()")
        result.fact("Duplicate rows", duplicates, "pandas duplicated().sum()")
        if quality.get("columns_with_missing_values"):
            result.fact(
                "Columns with missing values",
                ", ".join(quality["columns_with_missing_values"][:8]),
                "pandas isna()",
            )
        top_correlations = profile.get("top_correlations") or []
        if top_correlations:
            top = top_correlations[0]
            result.fact(
                "Strongest correlation",
                f"{top['column_a']} vs {top['column_b']}: {top['correlation']:.3f}",
                "Pearson correlation",
            )
        for stats in (profile.get("numeric_columns") or [])[:3]:
            result.fact(
                f"{stats['name']} mean",
                stats.get("mean"),
                "pandas mean",
            )
        result.context = {
            "profile_summary": profile.get("summary"),
            "overview": overview,
            "key_numeric_columns": [
                {"name": item["name"], "mean": item.get("mean"), "median": item.get("median")}
                for item in (profile.get("numeric_columns") or [])[:5]
            ],
            "top_categorical": [
                {"name": item["name"], "top_values": item.get("top_values", [])[:3]}
                for item in (profile.get("categorical_columns") or [])[:3]
            ],
            "top_correlations": top_correlations[:3],
            "quality_issues": profile.get("quality_issues", [])[:5],
        }
        return result

    def _unknown(self, message: str) -> QuestionResult:
        result = QuestionResult(
            question_type="unanswerable",
            answer=message,
            context={
                "available_numeric_columns": [str(c) for c in self.numeric_cols],
                "available_categorical_columns": [str(c) for c in self.categorical_cols],
                "available_datetime_columns": [str(c) for c in self.datetime_cols],
            },
        )
        result.fact(
            "Available numeric columns",
            ", ".join(str(c) for c in self.numeric_cols) or "none",
            "dataset schema",
        )
        result.fact(
            "Available categorical columns",
            ", ".join(str(c) for c in self.categorical_cols) or "none",
            "dataset schema",
        )
        return result

    @staticmethod
    def _has_aggregate_intent(text: str) -> bool:
        words = (
            "average",
            "mean",
            "avg",
            "median",
            "total",
            "sum",
            "combined",
            "overall",
            "count",
            "maximum",
            "max",
            "minimum",
            "min",
            "highest",
            "lowest",
            "largest",
            "smallest",
            "top",
            "least",
            "most",
        )
        if any(word in text for word in words):
            return True
        return any(alias in text for alias in _ALIASES)

    @staticmethod
    def _detect_aggregation(text: str, default: str) -> str:
        if any(word in text for word in ("average", "mean", "avg")):
            return "mean"
        if "median" in text:
            return "median"
        if any(word in text for word in ("total", "sum", "combined", "overall")):
            return "sum"
        if "count" in text or "how many" in text:
            return "count"
        if any(word in text for word in ("maximum", "max", "highest", "largest")):
            return "max"
        if any(word in text for word in ("minimum", "min", "lowest", "smallest")):
            return "min"
        return default

    @staticmethod
    def _strength(value: float) -> str:
        magnitude = abs(value)
        if magnitude >= 0.8:
            return "very strong"
        if magnitude >= 0.6:
            return "strong"
        if magnitude >= 0.4:
            return "moderate"
        if magnitude >= 0.2:
            return "weak"
        return "very weak"


def metric_label(column: str, aggregation: str) -> str:
    """Return a human-readable label for a grouped metric."""
    prefix = {
        "sum": "total",
        "mean": "average",
        "median": "median",
        "count": "count",
    }.get(aggregation, aggregation)
    return f"{prefix} {column}"
