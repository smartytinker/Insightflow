"""JSON serialization helpers for NumPy/pandas values.

FastAPI and the database cannot serialize NaN/Infinity or NumPy scalar types.
All analytical output passes through :func:`json_safe` before persistence.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd


def json_safe(value: Any) -> Any:
    """Recursively convert a value into JSON-compatible primitives.

    Missing values (NaN, NaT, pandas NA) become ``None``. Non-finite floats
    also become ``None`` so responses remain valid JSON.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [json_safe(item) for item in value.tolist()]
    if isinstance(value, (pd.Timestamp, datetime, date, time)):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.total_seconds()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, Decimal):
        number = float(value)
        return number if math.isfinite(number) else None
    if value is pd.NA or value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, str)):
        return value
    return str(value)
