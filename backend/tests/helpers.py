"""Shared test helpers and dataset builders."""

from __future__ import annotations

from typing import Any

import pandas as pd

SAMPLE_CSV = """transaction_date,category,region,revenue,quantity,customer_id
2024-01-01,Electronics,North,100.0,2,C1
2024-01-15,Electronics,South,250.5,3,C2
2024-02-01,Home,North,80.0,1,C1
2024-02-10,Home,West,120.0,2,C3
2024-03-01,Sports,East,60.0,1,C2
2024-03-15,Sports,West,90.0,2,C4
2024-04-01,Electronics,East,310.0,4,C5
2024-04-15,Home,South,,2,C1
2024-05-01,Sports,North,75.5,1,
2024-05-15,Electronics,West,200.0,3,C2
2024-05-15,Electronics,West,200.0,3,C2
"""

ANALYTICS_CSV = """value,quantity,group,when
10,1,A,2024-01-01
20,2,A,2024-02-01
30,3,B,2024-03-01
40,4,B,2024-04-01
50,5,B,2024-05-01
,6,C,2024-06-01
"""

CLEANING_CSV = """Name,Value,Category
alpha,10,A
alpha,10,A
beta,20,B
gamma,,B
delta,not-a-number,A
"""

CATEGORICAL_ONLY_CSV = """name,city
Alice,London
Bob,Paris
Cara,Rome
Dan,London
Eve,Paris
Finn,Rome
"""


def anomaly_csv(rows: int = 60) -> str:
    """Create a numeric dataset with two extreme observations."""
    lines = ["value,quantity,label"]
    for index in range(rows):
        value = 10 + (index % 5)
        lines.append(f"{value},{index % 4},normal-{index}")
    lines.append("1000,99,extreme-high")
    lines.append("-900,98,extreme-low")
    return "\n".join(lines) + "\n"


def many_rows_csv(rows: int = 20) -> str:
    lines = ["value,group"]
    for index in range(rows):
        lines.append(f"{index},{'A' if index % 2 == 0 else 'B'}")
    return "\n".join(lines) + "\n"


def dataframe_from_csv(content: str) -> pd.DataFrame:
    import io

    return pd.read_csv(io.StringIO(content))


def upload(client, content: str | bytes, filename: str = "test.csv") -> dict[str, Any]:
    """Upload a CSV through the API and return the parsed response."""
    payload = content.encode("utf-8") if isinstance(content, str) else content
    response = client.post(
        "/api/v1/datasets/upload",
        files={"file": (filename, payload, "text/csv")},
    )
    assert response.status_code == 201, response.text
    return response.json()
