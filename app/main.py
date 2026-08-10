import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from pydantic import ValidationError
from app.calculation import CalculationInput, calculate
from app.exporting import make_record, render_report
from app.request_limits import (
    RequestBodyLimitMiddleware,
    parse_max_request_body_bytes,
)
from app.records import (
    APP_VERSION,
    generate_management_number,
    is_valid_management_number,
    is_valid_tokyo_timestamp,
    tokyo_now,
)
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_FORM={"mode":"required_stock","title":"","material_type":"","author":"","notes":"","new_stock_length_mm":"","kerf_mm":"0","left_trim_mm":"10","new_stock_quantity":"0","part_lengths":[""],"part_quantities":[""],"remnant_lengths":[""],"remnant_quantities":[""]}


def is_production(app_env: str | None = None) -> bool:
    """Return whether the configured application environment is production."""
    value = os.getenv("APP_ENV", "") if app_env is None else app_env
    return value.strip().lower() == "production"


production = is_production()
app = FastAPI(
    title="Nesting1D",
    description="一次元ネスティング計算アプリ",
    version=APP_VERSION,
    docs_url=None if production else "/docs",
    redoc_url=None if production else "/redoc",
    openapi_url=None if production else "/openapi.json",
)

app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=parse_max_request_body_bytes(),
)


@app.middleware("http")
async def add_response_headers(request: Request, call_next):
    response = await call_next(request)

    # Route-specific values take precedence if a response already set a header.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )

    if response.headers.get("content-type", "").lower().startswith("text/html"):
        response.headers.setdefault("Cache-Control", "no-store")

    return response


app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(
    directory=BASE_DIR / "templates"
)


@app.get("/robots.txt", response_class=Response)
def robots_txt() -> Response:
    # This only asks search engines not to crawl; it is not access control.
    return Response(
        "User-agent: *\nDisallow: /\n",
        media_type="text/plain",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "form": DEFAULT_FORM,
            "errors": [],
            "field_errors": {},
            "result": None,
            "view": None,
            "input_snapshot": None,
            "calculated_at": None,
            "management_number": "",
            "management_number_state": "reissue",
            "created_at": "",
            "updated_at": "",
        },
    )


def _add_field_error(field_errors:dict[str,list[str]],key:str,message:str)->None:
    field_errors.setdefault(key,[]).append(message)

def _integer(value:str,label:str,minimum:int,maximum:int,errors:list[str],field_errors:dict[str,list[str]]|None=None,field_key:str|None=None,inline_label:str|None=None)->int|None:
    text=value.strip()
    if not text:
        errors.append(f"{label}を入力してください。")
        if field_errors is not None and field_key:
            _add_field_error(field_errors,field_key,f"{inline_label or label}を入力してください。")
        return None
    if not text.isdecimal():
        errors.append(f"{label}は{minimum}以上{maximum}以下の整数で入力してください。")
        if field_errors is not None and field_key:
            _add_field_error(field_errors,field_key,f"{minimum}以上{maximum}以下の整数を入力してください。")
        return None
    number=int(text)
    if not minimum<=number<=maximum:
        errors.append(f"{label}は{minimum}以上{maximum}以下で入力してください。")
        if field_errors is not None and field_key:
            _add_field_error(field_errors,field_key,f"{minimum}以上{maximum}以下の整数を入力してください。")
        return None
    return number

def _rows(lengths:list[str],quantities:list[str],label:str,errors:list[str],field_errors:dict[str,list[str]],length_key:str,quantity_key:str,length_label:str,quantity_label:str)->list[dict[str,int]]:
    rows=[]
    for index in range(max(len(lengths),len(quantities))):
        length=lengths[index] if index<len(lengths) else ""; quantity=quantities[index] if index<len(quantities) else ""
        if not length.strip() and not quantity.strip(): continue
        if not length.strip() or not quantity.strip():
            errors.append(f"{label}{index+1}行目は寸法と本数の両方を入力してください。")
            if not length.strip(): _add_field_error(field_errors,f"{length_key}_{index}",f"{length_label}を入力してください。")
            if not quantity.strip(): _add_field_error(field_errors,f"{quantity_key}_{index}",f"{quantity_label}を入力してください。")
        size=None if not length.strip() else _integer(length,f"{label}{index+1}行目の寸法",1,6_100,errors,field_errors,f"{length_key}_{index}",length_label)
        count=None if not quantity.strip() else _integer(quantity,f"{label}{index+1}行目の本数",1,500,errors,field_errors,f"{quantity_key}_{index}",quantity_label)
        if size is not None and count is not None: rows.append({"length_mm":size,"quantity":count})
    return rows

def _input_snapshot(mode:str,stock:int,kerf:int,trim:int,parts:list[dict[str,int]])->dict:
    quantities:dict[int,int]={}
    for part in parts:
        quantities[part["length_mm"]]=quantities.get(part["length_mm"],0)+part["quantity"]
    return {
        "mode_label":"在庫母材・残材活用" if mode=="inventory" else "必要母材算出",
        "new_stock_length_mm":stock,
        "kerf_mm":kerf,
        "left_trim_mm":trim,
        "part_type_count":len(parts),
        "part_total_quantity":sum(part["quantity"] for part in parts),
        "part_total_length_mm":sum(part["length_mm"]*part["quantity"] for part in parts),
        "parts_by_length":[{"length_mm":length,"quantity":quantity} for length,quantity in sorted(quantities.items(),reverse=True)],
    }

def _display_result(result,left_trim_mm:int,kerf_mm:int)->dict:
    source_labels={
        "existing_remnant":"在庫残材",
        "inventory_new_stock":"在庫新品材",
        "held_new_stock":"在庫新品材",
        "additional_new_stock":"購入新品材",
    }
    state_labels={"remnant":"発生残材","scrap":"廃棄材","used_up":"使い切り"}
    reason_labels={
        "NO_REQUIRED_PART_FITS_AFTER_TRIM":"左端を捨て切りした後の長さでは、必要な部材を1本も切り出せないため未使用",
        "NOT_SELECTED_BY_CANDIDATE_SELECTION":"候補選別の結果、使用しない計画が選ばれたため未使用",
        "NOT_NEEDED":"必要部材がすべて確保され、この在庫材料を使用する必要がないため",
    }
    usages=[]
    for number,usage in enumerate(result.stock_usage,1):
        item=dict(usage)
        item["stock_number"]=number
        item["source_label"]=source_labels.get(item["source_type"],item["source_type"])
        item["state_label"]=state_labels.get(item["remainder_class"],item["remainder_class"])
        usages.append(item)
    patterns=[]
    for pattern in result.patterns:
        item=dict(pattern)
        item["materials"]=[usage for usage in usages if usage["pattern_id"]==item["pattern_id"]]
        material_groups=[]
        for material in item["materials"]:
            group=next((group for group in material_groups if group["source_type"]==material["source_type"] and group["original_length_mm"]==material["original_length_mm"]),None)
            if group is None:
                group={"source_type":material["source_type"],"source_label":material["source_label"],"original_length_mm":material["original_length_mm"],"quantity":0}
                material_groups.append(group)
            group["quantity"]+=1
        item["material_groups"]=material_groups
        patterns.append(item)
    unused=[]
    for inventory in result.unused_inventory:
        item=dict(inventory)
        item["reason"]=reason_labels.get(item["reason_code"],"使用条件に合わないため未使用です")
        item["source_label"]=source_labels.get(item["source_type"],item["source_type"])
        unused.append(item)
    fulfillment=result.fulfillment
    required_total=sum(item["required_quantity"] for item in fulfillment)
    completed_total=sum(item["completed_total_quantity"] for item in fulfillment)
    return {
        "patterns":patterns,
        "usages":usages,
        "unused_inventory":unused,
        "remnant_total":sum(x["remaining_length_mm"] for x in usages if x["remainder_class"]=="remnant"),
        "scrap_total":sum(x["remaining_length_mm"] for x in usages if x["remainder_class"]=="scrap"),
        "used_up_count":sum(x["remainder_class"]=="used_up" for x in usages),
        "required_total":required_total,
        "completed_total":completed_total,
        "left_trim_mm":left_trim_mm,
        "kerf_mm":kerf_mm,
    }

@app.post("/",response_class=HTMLResponse)
async def calculate_from_form(request:Request)->HTMLResponse:
    raw=await request.form()
    requested_management_number=str(raw.get("result_management_number",""))
    management_number_state=str(raw.get("management_number_state","reissue"))
    requested_created_at=str(raw.get("result_created_at",""))
    requested_updated_at=str(raw.get("result_updated_at",""))
    form:dict[str,Any]={"mode":str(raw.get("mode","required_stock")),"title":str(raw.get("title","")),"material_type":str(raw.get("material_type","")),"author":str(raw.get("author","")),"notes":str(raw.get("notes","")),"new_stock_length_mm":str(raw.get("new_stock_length_mm","")),"kerf_mm":str(raw.get("kerf_mm","")),"left_trim_mm":str(raw.get("left_trim_mm","")),"new_stock_quantity":str(raw.get("new_stock_quantity","0")),"part_lengths":[str(x) for x in raw.getlist("part_length")],"part_quantities":[str(x) for x in raw.getlist("part_quantity")],"remnant_lengths":[str(x) for x in raw.getlist("remnant_length")],"remnant_quantities":[str(x) for x in raw.getlist("remnant_quantity")]}
    errors=[]; field_errors:dict[str,list[str]]={}; mode=form["mode"]
    for field, label, maximum in (("title","件名",20),("material_type","材料種類",30),("author","データ製作者",30),("notes","備考",400)):
        if len(form[field]) > maximum: errors.append(f"{label}は{maximum}文字以下で入力してください。")
    if mode not in {"required_stock","inventory"}: errors.append("計算モードを選択してください。")
    stock=_integer(form["new_stock_length_mm"],"新品母材長",1,6_100,errors,field_errors,"new_stock_length_mm","新品母材長")
    kerf=_integer(form["kerf_mm"],"鋸刃厚",0,100,errors,field_errors,"kerf_mm","鋸刃厚")
    trim=_integer(form["left_trim_mm"],"左端捨て切り寸法",0,100,errors,field_errors,"left_trim_mm","左端捨て切り寸法")
    parts=_rows(form["part_lengths"],form["part_quantities"],"必要部材",errors,field_errors,"part_length","part_quantity","寸法","必要本数")
    if not parts:
        errors.append("必要部材を最低1行入力してください。")
        if form["part_lengths"] and not form["part_lengths"][0].strip(): _add_field_error(field_errors,"part_length_0","寸法を入力してください。")
        if form["part_quantities"] and not form["part_quantities"][0].strip(): _add_field_error(field_errors,"part_quantity_0","必要本数を入力してください。")
    inventory=None
    if mode=="inventory":
        held=_integer(form["new_stock_quantity"],"在庫新品材本数",0,500,errors,field_errors,"new_stock_quantity","在庫本数")
        remnants=_rows(form["remnant_lengths"],form["remnant_quantities"],"在庫残材",errors,field_errors,"remnant_length","remnant_quantity","残材寸法","保有本数")
        if held is not None: inventory={"new_stock_quantity":held,"remnants":remnants}
    if None not in (stock,kerf,trim):
        impossible=[]
        for index,value in enumerate(form["part_lengths"]):
            if value.strip().isdecimal() and 1<=int(value)<=6_100 and trim+kerf+int(value)+kerf>stock:
                impossible.append(index)
                _add_field_error(field_errors,f"part_length_{index}","捨て切りと鋸刃厚を含めて新品母材から切り出せる寸法を入力してください。")
        if impossible: errors.append("新品母材から切り出せない部材があります。")
    result=None
    view=None
    input_snapshot=None
    calculated_at=None
    management_number=""
    created_at=""
    updated_at=""
    if not errors and None not in (stock,kerf,trim):
        payload={"mode":mode,"cutting_conditions":{"new_stock_length_mm":stock,"kerf_mm":kerf,"left_trim_mm":trim},"required_parts":parts}
        if mode=="inventory": payload["inventory"]=inventory
        try:
            result=calculate(CalculationInput.model_validate(payload)); view=_display_result(result,trim,kerf)
            input_snapshot=_input_snapshot(mode,stock,kerf,trim,parts)
            calculation_time=tokyo_now()
            calculated_at=calculation_time.strftime("%Y-%m-%d %H:%M:%S")
            maintain_identity=(
                management_number_state=="maintain"
                and is_valid_management_number(requested_management_number)
                and is_valid_tokyo_timestamp(requested_created_at)
                and is_valid_tokyo_timestamp(requested_updated_at)
            )
            if maintain_identity:
                management_number=requested_management_number
                created_at=requested_created_at
                updated_at=requested_updated_at
            else:
                management_number=generate_management_number(calculation_time)
                created_at=calculation_time.isoformat(timespec="seconds")
                updated_at=created_at
        except ValidationError: errors.append("入力行数が上限を超えています。入力を確認してください。")
        except ValueError as exc: errors.append(str(exc))
        except Exception: errors.append("計算中に予期しないエラーが発生しました。入力を確認して再度お試しください。")
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "form": form,
            "errors": errors,
            "field_errors": field_errors,
            "result": result,
            "view": view,
            "input_snapshot": input_snapshot,
            "calculated_at": calculated_at,
            "management_number": management_number,
            "management_number_state": "maintain" if management_number else "reissue",
            "created_at": created_at,
            "updated_at": updated_at,
        },
    )


def _saved_input(data: dict):
    payload = {key: data[key] for key in ("mode", "cutting_conditions", "required_parts")}
    if data["mode"] == "inventory":
        payload["inventory"] = data.get("inventory")
    calculation_input = CalculationInput.model_validate(payload)
    result = calculate(calculation_input)
    conditions = calculation_input.cutting_conditions
    return calculation_input, result, _display_result(
        result, conditions.left_trim_mm, conditions.kerf_mm
    )


def _export_error(message: str = "処理できませんでした。入力内容を確認してください。"):
    return JSONResponse({"ok": False, "message": message}, status_code=400)


def _build_export_record(body: dict):
    input_data = body["input"]
    number = str(body["management_number"])
    created_at = str(body["created_at"])
    updated_at = str(body["updated_at"])
    if (
        not is_valid_management_number(number)
        or not is_valid_tokyo_timestamp(created_at)
        or not is_valid_tokyo_timestamp(updated_at)
    ):
        raise ValueError("出力識別情報が正しくありません。")
    calculation_input, result, view = _saved_input(input_data)
    normalized_input = calculation_input.model_dump() | {
        "metadata": input_data.get("metadata", {})
    }
    record = make_record(
        number,
        tokyo_now(),
        normalized_input,
        result.model_dump(),
        created_at=created_at,
        updated_at=updated_at,
    )
    return record, view


@app.post("/api/export/json")
async def export_json(request: Request):
    try:
        body = await request.json()
        record, _ = _build_export_record(body)
        number = record["management_number"]
        return JSONResponse(
            record,
            headers={
                "Content-Disposition": f'attachment; filename="{number}.json"',
                "Cache-Control": "no-store",
            },
        )
    except (KeyError, TypeError, ValidationError, ValueError):
        return _export_error()
    except Exception:
        return _export_error()


@app.post("/api/export/html")
async def export_html(request: Request):
    try:
        body = await request.json()
        record, view = _build_export_record(body)
        number = record["management_number"]
        content = render_report(templates, record, view)
        return Response(
            content,
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{number}.html"',
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
            },
        )
    except (KeyError, TypeError, ValidationError, ValueError):
        return _export_error()
    except Exception:
        return _export_error()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
    }
