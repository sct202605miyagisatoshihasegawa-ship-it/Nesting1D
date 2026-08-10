# Nesting1D - 計算データモデル
# 役割: 計算入力・在庫・切断結果の構造と値制約をPydanticで定義する。
# 更新日: 2026-08-10

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Length = Annotated[int, Field(strict=True, ge=1, le=6_100)]
Count = Annotated[int, Field(strict=True, ge=1, le=500)]
PartCount = Annotated[int, Field(strict=True, ge=1, le=500)]
Condition = Annotated[int, Field(strict=True, ge=0, le=100)]

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Part(Model):
    length_mm: Length
    quantity: PartCount

class Remnant(Model):
    length_mm: Length
    quantity: Count

class Conditions(Model):
    new_stock_length_mm: Length
    kerf_mm: Condition
    left_trim_mm: Condition = 10

class Inventory(Model):
    new_stock_quantity: Annotated[int, Field(strict=True, ge=0, le=500)]
    remnants: list[Remnant] = Field(default_factory=list, max_length=10)

class CalculationInput(Model):
    mode: Literal["required_stock", "inventory"]
    cutting_conditions: Conditions
    required_parts: list[Part] = Field(min_length=1, max_length=20)
    inventory: Inventory | None = None

    @model_validator(mode="after")
    def valid(self):
        if (self.mode == "inventory") != (self.inventory is not None):
            raise ValueError("modeとinventoryが一致しません")
        return self

class CalculationResult(Model):
    mode: str
    required_stock_quantity: int
    additional_new_stock_required: int
    existing_remnant_used: int
    inventory_new_stock_used: int
    patterns: list[dict]
    stock_usage: list[dict]
    unused_inventory: list[dict]
    dimension_change_count: int
    initial_setup_count: int
    machine_setting_count: int
    fulfillment: list[dict]
