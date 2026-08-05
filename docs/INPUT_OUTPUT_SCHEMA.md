# Nesting1D 入出力スキーマ

## 1. 方針
計算ロジックはJSON互換構造を受け取り返す。キーは `snake_case`、長さ・本数は整数。本書は期待構造であり保存機能の実装仕様ではない。

## 2. 入力JSON
```json
{
  "format_version": "1.0",
  "mode": "inventory",
  "metadata": {"title": "案件A", "material_type": "角材", "author": "担当者", "notes": ""},
  "cutting_conditions": {
    "new_stock_length_mm": 1000,
    "kerf_mm": 0,
    "left_trim_mm": 0,
    "scrap_threshold_base_mm": 50
  },
  "required_parts": [
    {"length_mm": 600, "quantity": 1},
    {"length_mm": 400, "quantity": 1}
  ],
  "inventory": {
    "new_stock_quantity": 0,
    "remnants": [{"length_mm": 600, "quantity": 1}]
  }
}
```
`mode` は `required_stock` または `inventory`。前者では `inventory` を省略、後者では必須。新品母材長は1種類。

## 3. 成功JSON（例7に対応）
```json
{
  "status": "success",
  "format_version": "1.0",
  "mode": "inventory",
  "summary": {
    "inventory_new_stock_used": 0,
    "additional_new_stock_required": 1,
    "pattern_count": 1,
    "total_remnant_length_mm": 0,
    "total_scrap_length_mm": 0
  },
  "fulfillment": [
    {"length_mm": 600, "required_quantity": 1, "completed_from_inventory_quantity": 0, "completed_total_quantity": 1, "shortage_before_purchase_quantity": 1, "shortage_after_purchase_quantity": 0},
    {"length_mm": 400, "required_quantity": 1, "completed_from_inventory_quantity": 0, "completed_total_quantity": 1, "shortage_before_purchase_quantity": 1, "shortage_after_purchase_quantity": 0}
  ],
  "patterns": [
    {"pattern_id": "P01", "usage_count": 1, "parts": [{"length_mm": 600, "quantity": 1}, {"length_mm": 400, "quantity": 1}], "dimension_change_count": 1}
  ],
  "stock_usage": [
    {"stock_no": 1, "source_type": "additional_new_stock", "original_length_mm": 1000, "pattern_id": "P01", "cuts": [600, 400], "used_length_mm": 1000, "remaining_length_mm": 0, "remainder_class": "used_up"}
  ],
  "unused_inventory": [
    {"source_type": "existing_remnant", "length_mm": 600, "quantity": 1, "reason_code": "NOT_SELECTED_BY_CANDIDATE_SELECTION"}
  ],
  "optimization": {"optimality": "best_among_generated_candidates", "complete_mathematical_optimum_guaranteed": false}
}
```

## 4. エラーJSON
```json
{
  "status": "validation_error",
  "errors": [{"path": "required_parts[0].quantity", "code": "OUT_OF_RANGE", "message": "必要本数は1以上100000以下で入力してください"}]
}
```
検証エラー時は計算結果を返さない。新品母材から切れない場合は `status: calculation_error`、コード `PART_DOES_NOT_FIT_NEW_STOCK` とする。

## 5. 列挙値
- `source_type`: `existing_remnant`, `inventory_new_stock`, `additional_new_stock`
- `remainder_class`: `remnant`, `scrap`, `used_up`
- `reason_code`: `NO_REQUIRED_PART_FITS_AFTER_TRIM`, `NOT_SELECTED_BY_CANDIDATE_SELECTION`, `NOT_NEEDED`

`reason_code`はJSONへコード値を保存する。`NOT_SELECTED_BY_CANDIDATE_SELECTION`は画面とHTMLで「候補選別の結果、使用しない計画が選ばれたため未使用」と表示する。
- `optimality`: `best_among_generated_candidates`

## 6. 公開版V1の出力レコード
管理番号、作成日時、更新日時は保存番号ではなく計算結果の識別情報であり、純粋な計算入力へ含めない。計算成功時にブラウザ状態へ設定し、JSON・HTMLの直接出力APIへ同じ値を渡す。

```json
{
  "format_version": "1.0",
  "app_version": "0.1.0",
  "management_number": "NEST-20260805-103645-A7K2",
  "created_at": "2026-08-05T10:36:45+09:00",
  "updated_at": "2026-08-05T10:36:45+09:00",
  "input": {
    "mode": "required_stock",
    "metadata": {"title": "", "material_type": "", "author": "", "notes": ""},
    "cutting_conditions": {"new_stock_length_mm": 1000, "kerf_mm": 3, "left_trim_mm": 10},
    "required_parts": [{"length_mm": 400, "quantity": 2}]
  },
  "calculation_result": {}
}
```

- 新形式は `NEST-YYYYMMDD-HHMMSS-XXXX`。日時は `Asia/Tokyo` のオフセット付きISO 8601。
- 旧形式 `NEST-YYYYMMDD-NNN` も `format_version: 1.0` の読込互換対象とする。
- JSON内の`calculation_result`は読込時に画面結果として信用せず、`input`を現行エンジンで再計算する。

## 7. 公開版V1のデータ経路
- `POST /api/export/json`：レコードをメモリ生成し、JSONレスポンスとして直接返す。
- `POST /api/export/html`：同じ識別情報・入力・再計算結果からHTMLをメモリ生成し、直接返す。
- 両レスポンスはキャッシュ抑止し、サーバー上へ実ファイル・一時ファイルを作成しない。
- 端末JSONはブラウザのFile APIで読み込み、ファイル本体をHTTP送信しない。
- サーバー保存、保存履歴、上書き、管理番号検索、保存済みデータ再読込はスキーマ外かつ公開版V1非対応。
