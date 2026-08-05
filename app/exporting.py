from copy import deepcopy
from datetime import datetime
from typing import Any

from fastapi.templating import Jinja2Templates

from app.records import APP_VERSION, FORMAT_VERSION

def make_record(number: str, now: datetime, calculation_input: dict[str, Any], calculation_result: dict[str, Any], *, created_at: str | None = None, updated_at: str | None = None) -> dict[str, Any]:
    timestamp = updated_at or now.isoformat()
    return {
        "format_version": FORMAT_VERSION,
        "app_version": APP_VERSION,
        "management_number": number,
        "created_at": created_at or timestamp,
        "updated_at": timestamp,
        "input": deepcopy(calculation_input),
        "calculation_result": deepcopy(calculation_result),
    }

def render_report(templates: Jinja2Templates, record: dict[str, Any], view: dict[str, Any]) -> str:
    return templates.get_template("report.html").render(
        record=deepcopy(record),
        data=record["input"],
        result=record["calculation_result"],
        view=view,
    )
