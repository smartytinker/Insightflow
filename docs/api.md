# API Documentation

Base URL (local): `http://localhost:8000`

Interactive documentation: `GET /docs` (Swagger UI) and `GET /redoc`.

All application endpoints are under `/api/v1`. Requests and responses are JSON unless noted. Uploads use `multipart/form-data`.

## Conventions

### Error envelope

Every handled error returns:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Unknown request columns: nope.",
    "details": {"missing_columns": ["nope"]},
    "request_id": "2f7d6f6f-0d2b-4f37-b2aa-0d6f5b31b9c4"
  }
}
```

| Status | Typical codes |
|---|---|
| 400 | `validation_error` |
| 404 | `not_found` |
| 409 | `conflict` |
| 413 | `file_too_large` |
| 415 | `unsupported_file_type` |
| 422 | `request_validation_error` |
| 500 | `internal_error` |
| 503 | `llm_unavailable`, `llm_not_configured` |

Every response includes `X-Request-ID`. Server stack traces are never returned.

### Pagination

List endpoints accept `limit` and `offset`:

```bash
curl "http://localhost:8000/api/v1/datasets?limit=20&offset=0"
```

Dataset lists return `{ "items": [...], "total": 3, "limit": 20, "offset": 0 }`. Previews return the same shape plus `columns`, `rows`, `total_rows` and `source`.

---

## Health and overview

### `GET /health`

```json
{
  "status": "ok",
  "database": "ok",
  "version": "1.0.0",
  "llm_configured": false
}
```

Returns 503 if the database is unreachable.

### `GET /api/v1/overview`

Dashboard metrics derived from persisted records:

```json
{
  "stats": {
    "total_datasets": 2,
    "total_records": 1179,
    "total_anomalies": 38,
    "datasets_with_analysis": 2,
    "total_analyses": 6,
    "total_chat_messages": 4
  },
  "recent_datasets": [ ... ],
  "recent_activity": [
    {
      "dataset_id": "8054...",
      "dataset_name": "sales.csv",
      "activity_type": "anomaly_detection",
      "description": "38 anomalies detected in 750 records",
      "created_at": "2026-11-19T18:11:00",
      "details": {"anomaly_id": 1, "anomaly_percentage": 5.07}
    }
  ]
}
```

`total_anomalies` sums the **latest** run per dataset, not every historical run.

---

## Datasets

### `POST /api/v1/datasets/upload`

```bash
curl -X POST http://localhost:8000/api/v1/datasets/upload \
  -F "file=@sample_data/sales.csv;type=text/csv"
```

Response `201 Created`:

```json
{
  "dataset": {
    "id": "805437e4-1645-429f-8982-b99cb7fa0740",
    "filename": "8054..._sales.csv",
    "original_filename": "sales.csv",
    "file_size": 58270,
    "row_count": 759,
    "column_count": 9,
    "upload_timestamp": "2026-11-19T18:06:26",
    "processing_status": "ready",
    "is_cleaned": false,
    "cleaned_row_count": null
  },
  "quality": {
    "total_rows": 759,
    "total_columns": 9,
    "missing_cells": 76,
    "missing_percentage": 1.11,
    "duplicate_rows": 9,
    "columns_with_missing_values": ["region", "unit_price", "customer_id"],
    "columns_with_duplicate_names": 0
  },
  "columns": [
    {
      "name": "revenue",
      "dtype": "float64",
      "kind": "numeric",
      "missing_count": 15,
      "missing_percentage": 1.98,
      "unique_count": 682,
      "sample_values": [42.47, 4041.04],
      "is_numeric": true,
      "is_datetime": false
    }
  ]
}
```

Validation failures:

- `415 unsupported_file_type` for non-CSV extensions.
- `413 file_too_large` when `MAX_UPLOAD_SIZE_MB` is exceeded.
- `400 validation_error` for empty/corrupt files, missing headers, duplicate columns, invalid encodings/binary content or exceeding row limits.

### `GET /api/v1/datasets`

Paginated metadata list.

### `GET /api/v1/datasets/{dataset_id}`

Metadata plus `columns`, `checksum` and optional quality. `quality` is `null` on this endpoint; use `/profile` for full quality information.

### `DELETE /api/v1/datasets/{dataset_id}`

Returns `204 No Content`. Deletes the original file, cleaned copy, cleaning operations, analyses, anomaly runs and chat sessions/messages.

### `GET /api/v1/datasets/{dataset_id}/preview?limit=20&offset=0`

```json
{
  "dataset_id": "8054...",
  "columns": ["transaction_id", "transaction_date", "..."],
  "rows": [{"transaction_id": "TXN-100393", "revenue": 42.47}],
  "total_rows": 759,
  "limit": 20,
  "offset": 0,
  "source": "original"
}
```

`source` is `cleaned` after a cleaning run. Dates are serialized as ISO strings.

---

## Cleaning

### `POST /api/v1/datasets/{dataset_id}/clean`

```bash
curl -X POST http://localhost:8000/api/v1/datasets/$ID/clean \
  -H 'Content-Type: application/json' \
  -d '{
    "drop_duplicates": true,
    "missing_strategy": "fill_median",
    "column_strategies": {"customer_id": "fill_mode"},
    "type_conversions": {"transaction_date": "datetime"},
    "normalize_columns": true,
    "column_case": "snake",
    "drop_columns": [],
    "outlier_action": "clip",
    "outlier_columns": ["revenue"],
    "outlier_iqr_multiplier": 1.5
  }'
```

Supported missing strategies: `none`, `drop_rows`, `fill_mean`, `fill_median`, `fill_mode`, `fill_constant`, `fill_zero`.

Supported conversions: `numeric`, `datetime`, `string`, `category`, `boolean`.

Outlier actions: `none`, `clip`, `remove` (IQR method).

Response:

```json
{
  "dataset_id": "8054...",
  "original_row_count": 759,
  "final_row_count": 750,
  "original_column_count": 9,
  "final_column_count": 9,
  "missing_values_before": 76,
  "missing_values_after": 59,
  "missing_values_filled": 15,
  "duplicates_removed": 9,
  "columns_transformed": [],
  "operations": [
    {
      "id": 1,
      "operation_type": "drop_duplicates",
      "operation_details": {"kept": "first"},
      "records_affected": 9,
      "created_at": "2026-11-19T18:11:00"
    }
  ],
  "warnings": [],
  "before_preview": [ ... ],
  "after_preview": [ ... ],
  "cleaned_file_available": true,
  "generated_at": "2026-11-19T18:11:00+00:00"
}
```

### `GET /api/v1/datasets/{dataset_id}/cleaning-history`

Returns all recorded operations, newest first.

---

## Analytics

### `GET /api/v1/datasets/{dataset_id}/profile?refresh=false`

Returns the full profile:

- `overview`: rows, columns, type counts, missing cells, duplicate rows, memory usage.
- `quality`: data quality summary and affected columns.
- `numeric_columns`: count, missingness, mean, median, std, min/max, quartiles, IQR, skewness, outlier count, histogram bins.
- `categorical_columns`: unique counts, top values with percentages.
- `datetime_columns`: min/max and span.
- `correlations`: columns + matrix (nullable values for undefined correlations).
- `top_correlations`: strongest pairs with strength labels.
- `time_series`: detected date/metric, aggregation, granularity, points.
- `quality_issues`, `important_columns`, `summary`.

`refresh=true` recomputes instead of using the stored cache.

### `GET /api/v1/datasets/{dataset_id}/statistics?refresh=false`

A lighter view of the same profile: overview, numeric/categorical/datetime stats, correlations and a `column -> missing count` map.

---

## Anomaly detection

### `POST /api/v1/datasets/{dataset_id}/anomalies`

```bash
curl -X POST http://localhost:8000/api/v1/datasets/$ID/anomalies \
  -H 'Content-Type: application/json' \
  -d '{
    "contamination": 0.05,
    "n_estimators": 100,
    "random_state": 42,
    "features": ["quantity", "unit_price", "revenue"]
  }'
```

- `contamination`: `(0, 0.5)`, default `0.05`.
- `n_estimators`: `10–1000`, default `100`.
- `features`: optional; must be numeric columns with variation. Omit to use all eligible numeric columns.

Response `201 Created` includes:

```json
{
  "id": 1,
  "dataset_id": "8054...",
  "generated_at": "2026-11-19T18:11:00+00:00",
  "source": "cleaned",
  "total_records": 750,
  "anomalies_detected": 38,
  "anomaly_percentage": 5.07,
  "contamination": 0.05,
  "n_estimators": 100,
  "random_state": 42,
  "features": ["quantity", "unit_price", "revenue"],
  "records_analyzed": 750,
  "records_excluded": 0,
  "anomalies": [
    {
      "row_number": 679,
      "anomaly_score": 0.304986,
      "is_anomaly": true,
      "rank": 1,
      "values": {"transaction_id": "TXN-100401", "revenue": 49155.2, "...": "..."}
    }
  ],
  "anomalies_returned": 38,
  "anomalies_truncated": false,
  "score_distribution": [{"start": -0.1, "end": 0.0, "count": 120}],
  "feature_statistics": {"mean": {"revenue": 1039.37}, "...": {}},
  "interpretation": "The model analysed ...",
  "disclaimer": "Anomalies are statistical outliers ..."
}
```

`row_number` is the CSV row position including the header (so it can be traced back to the uploaded file). The first 2,000 anomalies are stored; `anomalies_truncated` reports when more were found.

### `GET /api/v1/datasets/{dataset_id}/anomalies`

Latest persisted run. Returns `400 validation_error` if no run exists.

### `GET /api/v1/datasets/{dataset_id}/anomalies/history`

List of runs with model configuration and counts.

### `GET /api/v1/datasets/{dataset_id}/anomalies/{run_id}`

A specific run, scoped to the dataset.

---

## AI assistant

### `POST /api/v1/datasets/{dataset_id}/chat`

```bash
curl -X POST http://localhost:8000/api/v1/datasets/$ID/chat \
  -H 'Content-Type: application/json' \
  -d '{"question": "Which category has the highest revenue?"}'
```

```json
{
  "session_id": "5904f314-7959-4859-a9a3-a85286d4c3e2",
  "message_id": 2,
  "answer": "By total revenue, the highest category is 'Electronics' at 379,955.67. ...",
  "mode": "calculations_only",
  "calculated_facts": [
    {"label": "Grouped by", "value": "category", "method": "categorical column"},
    {"label": "Top category by total revenue", "value": "Electronics (379,955.67)", "method": "pandas groupby ranking"}
  ],
  "question_type": "group_aggregate",
  "llm_error": "LLM provider is not configured.",
  "note": "AI interpretation is unavailable because no LLM provider is configured. The answer above was calculated directly from your dataset.",
  "created_at": "2026-11-19T18:12:00"
}
```

`mode` is `llm+calculations` when the provider returned an interpretation, otherwise `calculations_only`.

Question types: `aggregate`, `group_aggregate`, `distribution`, `count`, `correlation`, `trend`, `outlier_scan`, `summary`, `unanswerable`.

### `GET /api/v1/datasets/{dataset_id}/chat/history?session_id=...`

Messages for the session (or the latest session when omitted). Assistant `message_metadata` contains `mode`, `facts`, `table`, `columns_used`, `llm_error` and `note`.

### `GET /api/v1/datasets/{dataset_id}/chat/sessions`

List conversations with message counts.

### `POST /api/v1/datasets/{dataset_id}/chat/sessions`

Creates a new empty conversation (`201`). Pass its `id` as `session_id` on future questions.

---

## Reports and downloads

### `GET /api/v1/datasets/{dataset_id}/report`

Consolidated JSON report containing dataset metadata, cleaning history, the latest profile, anomaly summary, chat activity and download paths.

### `GET /api/v1/datasets/{dataset_id}/report/dataset.csv`

Downloads the active dataset (cleaned copy if available). `Content-Disposition: attachment`.

### `GET /api/v1/datasets/{dataset_id}/report/quality.csv`

Column-level quality export: dtype, missing count/percentage, unique count.

### `GET /api/v1/datasets/{dataset_id}/report/anomalies.csv`

Downloads stored anomaly records with `row_number`, `anomaly_score`, `rank` and all original columns. Returns `400 validation_error` when no anomaly run exists.

---

## Status code summary

| Operation | Success | Common failures |
|---|---|---|
| Upload | 201 | 400, 413, 415, 422 |
| List/get dataset | 200 | 404 |
| Delete dataset | 204 | 404 |
| Clean | 200 | 400, 404 |
| Profile/statistics | 200 | 400, 404 |
| Run anomalies | 201 | 400, 404 |
| Get anomalies | 200 | 400 (no run), 404 |
| Chat | 200 | 400, 404, 422, 503 (LLM fallback handled internally) |
| Report/downloads | 200 | 400, 404 |

LLM unavailability does **not** fail a chat request; it returns `200` with `mode = "calculations_only"` and a note. The `LLMUnavailableError`/`LLMNotConfiguredError` types (503) are used internally by the service layer; the chat orchestration converts them into a grounded fallback response instead of surfacing an error to the user.
