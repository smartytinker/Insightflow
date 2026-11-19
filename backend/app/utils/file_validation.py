"""Upload validation and safe CSV parsing.

Security notes:
- Only ``.csv`` files are accepted.
- Filenames are reduced to a safe basename; no user-controlled paths are used.
- Files are parsed from an in-memory buffer before being written to disk.
- Size limits are enforced before parsing.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from pathlib import Path

import pandas as pd

from app.core.config import Settings
from app.core.exceptions import (
    FileTooLargeError,
    UnsupportedFileTypeError,
    ValidationAppError,
)

_ALLOWED_EXTENSIONS = {".csv"}
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def sanitize_filename(filename: str | None) -> str:
    """Return a safe basename for an uploaded file.

    Strips directory components (path traversal), control characters and
    characters that are unsafe in filesystem paths.
    """
    if not filename:
        raise ValidationAppError("A filename is required.")
    # Normalize and keep only the final path component, handling both separators.
    normalized = unicodedata.normalize("NFKC", filename).replace("\\", "/")
    base = normalized.split("/")[-1].strip()
    base = _SAFE_FILENAME_RE.sub("_", base).strip("._")
    if not base:
        raise ValidationAppError("The uploaded filename is not valid.")
    if len(base) > 120:
        stem = Path(base).stem[:100]
        base = f"{stem}.csv"
    suffix = Path(base).suffix.lower()
    if suffix != ".csv":
        base = f"{Path(base).stem}.csv"
    return base


def validate_uploads(
    filename: str | None,
    content: bytes,
    settings: Settings,
    content_type: str | None = None,
) -> str:
    """Validate extension, size and basic content. Returns the safe filename."""
    if not filename:
        raise ValidationAppError("A CSV file is required.")
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{suffix or 'unknown'}'. Only .csv files are accepted.",
            details={"allowed_extensions": sorted(_ALLOWED_EXTENSIONS)},
        )
    if (
        content_type
        and "csv" not in content_type.lower()
        and content_type
        not in (
            "application/octet-stream",
            "text/plain",
        )
    ):
        # Browsers occasionally send generic types; extension remains authoritative.
        pass
    if not content:
        raise ValidationAppError("The uploaded file is empty.")
    if len(content) > settings.max_upload_size_bytes:
        raise FileTooLargeError(
            f"The file exceeds the {settings.max_upload_size_mb} MB upload limit.",
            details={
                "max_size_mb": settings.max_upload_size_mb,
                "received_bytes": len(content),
            },
        )
    if b"\x00" in content[:4096]:
        raise ValidationAppError("The file appears to be binary, not a CSV text file.")

    safe_name = sanitize_filename(filename)
    return safe_name


def _decode(content: bytes) -> tuple[str, str]:
    """Decode bytes using common CSV encodings and return (text, encoding)."""
    for encoding in _ENCODINGS:
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValidationAppError(
        "The file encoding could not be detected. Please save the CSV as UTF-8."
    )


def _read_header(text: str) -> list[str]:
    """Read and validate the header row, including duplicate detection."""
    sample = text[:65536]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;|\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValidationAppError("The CSV file has no header row.") from exc

    cleaned = [str(name).strip() for name in header]
    if not cleaned or all(name == "" for name in cleaned):
        raise ValidationAppError("The CSV file has no header row.")
    if any(name == "" for name in cleaned):
        raise ValidationAppError("The CSV header contains empty column names.")
    duplicates = sorted({name for name in cleaned if cleaned.count(name) > 1})
    if duplicates:
        raise ValidationAppError(
            "The CSV file contains duplicate column names.",
            details={"duplicate_columns": duplicates},
        )
    return cleaned


def parse_csv_bytes(content: bytes, settings: Settings) -> tuple[pd.DataFrame, str]:
    """Parse CSV bytes into a DataFrame with validation.

    Returns the dataframe and the detected encoding. Raises domain exceptions
    with actionable messages for empty, corrupt or oversized files.
    """
    text, encoding = _decode(content)
    if not text.strip():
        raise ValidationAppError("The CSV file is empty.")
    header = _read_header(text)

    try:
        delimiter = ","
        try:
            delimiter = csv.Sniffer().sniff(text[:65536], delimiters=",;|\t").delimiter
        except csv.Error:
            delimiter = ","

        df = pd.read_csv(
            io.StringIO(text),
            sep=delimiter,
            dtype=str,
            keep_default_na=True,
            na_values=["", "NA", "N/A", "na", "n/a", "NULL", "null", "None"],
            skip_blank_lines=True,
            on_bad_lines="error",
            engine="python",
        )
    except pd.errors.EmptyDataError as exc:
        raise ValidationAppError("The CSV file is empty or missing a header row.") from exc
    except (pd.errors.ParserError, csv.Error) as exc:
        raise ValidationAppError(
            "The CSV file is corrupted or malformed and could not be parsed."
        ) from exc
    except UnicodeDecodeError as exc:
        raise ValidationAppError("The CSV file contains invalid text encoding.") from exc

    df.columns = header[: len(df.columns)]
    if len(header) != len(df.columns):
        raise ValidationAppError("The CSV header and row widths do not match.")
    if df.empty:
        raise ValidationAppError("The CSV file contains a header but no data rows.")
    if len(df) > settings.max_dataset_rows:
        raise ValidationAppError(
            f"The dataset exceeds the {settings.max_dataset_rows:,} row limit.",
            details={"max_rows": settings.max_dataset_rows, "rows": len(df)},
        )
    if df.shape[1] == 0:
        raise ValidationAppError("The CSV file has no columns.")

    # Coerce obvious numeric and date columns while preserving original text.
    df = coerce_dataframe(df)
    return df, encoding


def coerce_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Convert all-text CSV columns into numeric/datetime where reliable.

    Conversion is conservative: a column is only converted when at least 95%
    of its non-null values parse successfully.
    """
    for column in df.columns:
        series = df[column]
        non_null = series.dropna()
        if non_null.empty:
            continue
        numeric = pd.to_numeric(non_null, errors="coerce")
        if numeric.notna().mean() >= 0.95:
            df[column] = pd.to_numeric(series, errors="coerce")

    # Detect date-like columns by name or value pattern.
    from app.utils.data_validation import infer_datetime_columns

    return infer_datetime_columns(df)


def compute_checksum(content: bytes) -> str:
    """Return a SHA-256 checksum for upload integrity tracking."""
    return hashlib.sha256(content).hexdigest()
