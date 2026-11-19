"""Dataset report and CSV export endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_dataset, get_report_service
from app.models.dataset import Dataset
from app.services.report_service import ReportService

router = APIRouter(prefix="/datasets", tags=["reports"])


@router.get(
    "/{dataset_id}/report",
    summary="Get a consolidated JSON report",
)
def get_report(
    dataset: Dataset = Depends(get_dataset),
    service: ReportService = Depends(get_report_service),
) -> dict:
    return service.build_report(dataset)


def _csv_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{dataset_id}/report/dataset.csv",
    summary="Download the active dataset as CSV",
    response_class=Response,
)
def download_dataset_csv(
    dataset: Dataset = Depends(get_dataset),
    service: ReportService = Depends(get_report_service),
) -> Response:
    content, filename = service.dataset_csv(dataset)
    return _csv_response(content, filename)


@router.get(
    "/{dataset_id}/report/anomalies.csv",
    summary="Download detected anomalies as CSV",
    response_class=Response,
)
def download_anomalies_csv(
    dataset: Dataset = Depends(get_dataset),
    service: ReportService = Depends(get_report_service),
) -> Response:
    content, filename = service.anomaly_csv(dataset)
    return _csv_response(content, filename)


@router.get(
    "/{dataset_id}/report/quality.csv",
    summary="Download a column-level data quality report as CSV",
    response_class=Response,
)
def download_quality_csv(
    dataset: Dataset = Depends(get_dataset),
    service: ReportService = Depends(get_report_service),
) -> Response:
    import csv
    import io

    rows = service.data_quality_rows(dataset)
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    filename = f"insightflow_quality_{dataset.id[:8]}.csv"
    return _csv_response(buffer.getvalue().encode("utf-8"), filename)
