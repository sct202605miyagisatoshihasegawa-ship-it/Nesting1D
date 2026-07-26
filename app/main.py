from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from pydantic import ValidationError
from app.calculation import CalculationInput, calculate
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_FORM={"mode":"required_stock","title":"","material_type":"","author":"","notes":"","new_stock_length_mm":"","kerf_mm":"0","left_trim_mm":"10","new_stock_quantity":"0","part_lengths":[""],"part_quantities":[""],"remnant_lengths":[""],"remnant_quantities":[""]}


app = FastAPI(
    title="Nesting1D",
    description="一次元ネスティング計算アプリ",
    version="0.1.0",
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(
    directory=BASE_DIR / "templates"
)


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"form":DEFAULT_FORM,"errors":[],"result":None,"view":None},
    )


def _integer(value:str,label:str,minimum:int,maximum:int,errors:list[str])->int|None:
    text=value.strip()
    if not text:
        errors.append(f"{label}を入力してください。"); return None
    if not text.isdecimal():
        errors.append(f"{label}は{minimum}以上{maximum}以下の整数で入力してください。"); return None
    number=int(text)
    if not minimum<=number<=maximum:
        errors.append(f"{label}は{minimum}以上{maximum}以下で入力してください。"); return None
    return number

def _rows(lengths:list[str],quantities:list[str],label:str,errors:list[str])->list[dict[str,int]]:
    rows=[]
    for index in range(max(len(lengths),len(quantities))):
        length=lengths[index] if index<len(lengths) else ""; quantity=quantities[index] if index<len(quantities) else ""
        if not length.strip() and not quantity.strip(): continue
        if not length.strip() or not quantity.strip():
            errors.append(f"{label}{index+1}行目は寸法と本数の両方を入力してください。"); continue
        size=_integer(length,f"{label}{index+1}行目の寸法",1,1_000_000,errors)
        count=_integer(quantity,f"{label}{index+1}行目の本数",1,100_000,errors)
        if size is not None and count is not None: rows.append({"length_mm":size,"quantity":count})
    return rows

def _display_result(result,form:dict)->dict:
    source_labels={
        "existing_remnant":"既存残材",
        "inventory_new_stock":"保有新品母材",
        "held_new_stock":"保有新品母材",
        "additional_new_stock":"追加購入新品母材",
    }
    state_labels={"remnant":"残材","scrap":"廃棄材","used_up":"使い切り"}
    reason_labels={
        "NO_REQUIRED_PART_FITS_AFTER_TRIM":"左端を捨て切りした後の長さでは、必要な部材を1本も切り出せないため未使用",
        "NOT_SELECTED_TO_AVOID_EXTRA_PURCHASE":"使用すると追加購入する新品母材が増えるため未使用",
        "NOT_NEEDED":"必要部材をすべて確保できたため未使用",
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
        "left_trim_mm":form["left_trim_mm"],
        "kerf_mm":form["kerf_mm"],
    }

@app.post("/",response_class=HTMLResponse)
async def calculate_from_form(request:Request)->HTMLResponse:
    raw=await request.form()
    form:dict[str,Any]={"mode":str(raw.get("mode","required_stock")),"title":str(raw.get("title","")),"material_type":str(raw.get("material_type","")),"author":str(raw.get("author","")),"notes":str(raw.get("notes","")),"new_stock_length_mm":str(raw.get("new_stock_length_mm","")),"kerf_mm":str(raw.get("kerf_mm","")),"left_trim_mm":str(raw.get("left_trim_mm","")),"new_stock_quantity":str(raw.get("new_stock_quantity","0")),"part_lengths":[str(x) for x in raw.getlist("part_length")],"part_quantities":[str(x) for x in raw.getlist("part_quantity")],"remnant_lengths":[str(x) for x in raw.getlist("remnant_length")],"remnant_quantities":[str(x) for x in raw.getlist("remnant_quantity")]}
    errors=[]; mode=form["mode"]
    if mode not in {"required_stock","inventory"}: errors.append("計算モードを選択してください。")
    stock=_integer(form["new_stock_length_mm"],"新品母材長",1,1_000_000,errors)
    kerf=_integer(form["kerf_mm"],"鋸刃厚",0,10_000,errors)
    trim=_integer(form["left_trim_mm"],"左端捨て切り寸法",0,10_000,errors)
    parts=_rows(form["part_lengths"],form["part_quantities"],"必要部材",errors)
    if not parts: errors.append("必要部材を最低1行入力してください。")
    inventory=None
    if mode=="inventory":
        held=_integer(form["new_stock_quantity"],"保有新品母材本数",0,100_000,errors)
        remnants=_rows(form["remnant_lengths"],form["remnant_quantities"],"既存残材",errors)
        if held is not None: inventory={"new_stock_quantity":held,"remnants":remnants}
    result=None
    view=None
    if not errors and None not in (stock,kerf,trim):
        payload={"mode":mode,"cutting_conditions":{"new_stock_length_mm":stock,"kerf_mm":kerf,"left_trim_mm":trim},"required_parts":parts}
        if mode=="inventory": payload["inventory"]=inventory
        try:
            result=calculate(CalculationInput.model_validate(payload)); view=_display_result(result,form)
        except ValidationError: errors.append("入力件数または合計本数が上限を超えています。入力を確認してください。")
        except ValueError as exc: errors.append(str(exc))
        except Exception: errors.append("計算中に予期しないエラーが発生しました。入力を確認して再度お試しください。")
    return templates.TemplateResponse(request=request,name="index.html",context={"form":form,"errors":errors,"result":result,"view":view})


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
    }
