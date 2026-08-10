# Nesting1D V1.0.1 入出力データ契約

- 対象アプリバージョン：1.0.1
- JSON形式バージョン：1.0
- 更新日：2026-08-10

## 1. 文書の目的

この文書は、Nesting1D V1.0.1における入力、端末JSON出力・読込、計算結果、HTML出力、HTTP APIのデータ契約を説明する。

- 機能と利用上の正式仕様： [REQUIREMENTS.md](REQUIREMENTS.md)
- 計算・切断ルール： [CALCULATION_RULES.md](CALCULATION_RULES.md)
- 設計理由： [DECISIONS.md](DECISIONS.md)

キー名は `snake_case`、寸法単位はmmである。数値入力とJSON内の寸法・本数は整数として扱う。

---

## 2. バージョン契約

| フィールド | 現行値 | 役割 |
|---|---|---|
| `app_version` | `"1.0.1"` | JSONを生成したNesting1Dアプリケーションのバージョン |
| `format_version` | `"1.0"` | 保存JSON構造の読込互換性を判断する形式バージョン |

`APP_VERSION`と`FORMAT_VERSION`は独立して管理する。V1.0.1はアプリケーションのパッチ更新であり、JSON構造に互換性を壊す変更がないため、`format_version`は`1.0`を維持する。

端末JSON読込では、`format_version == "1.0"`を必須とする。`app_version`は文字列であることを確認するが、読込互換性の判定値には使用しない。このため、同じ形式バージョンを使用する旧アプリ版のJSONも、ほかの検証条件を満たせば読み込める。

---

## 3. 入力データ

### 3.1 計算入力の全体構造

```json
{
  "mode": "inventory",
  "metadata": {
    "title": "案件A",
    "material_type": "角材",
    "author": "担当者",
    "notes": ""
  },
  "cutting_conditions": {
    "new_stock_length_mm": 6000,
    "kerf_mm": 3,
    "left_trim_mm": 10
  },
  "required_parts": [
    {"length_mm": 1200, "quantity": 4}
  ],
  "inventory": {
    "new_stock_quantity": 2,
    "remnants": [
      {"length_mm": 2500, "quantity": 1}
    ]
  }
}
```

`mode`は次のいずれかである。

- `required_stock`：必要母材算出モード
- `inventory`：在庫母材・残材活用モード

`inventory`は在庫モードでは必須である。必要母材算出モードでは省略または`null`とし、非nullの在庫オブジェクトは受け付けない。アプリが出力する必要母材算出モードのJSONでは、正規化後の`inventory: null`が含まれる。

### 3.2 共通情報

共通情報は計算結果へ影響しない任意文字入力である。フォームでは空文字を許容し、JSONでは`metadata`オブジェクトと4フィールドを保持する。各値は文字列であり、`null`は使用しない。

| 表示項目 | JSONフィールド | 型 | 必須 | 空文字 | 最大文字数 |
|---|---|---|---|---|---:|
| 件名 | `metadata.title` | string | フィールド必須 | 可 | 20 |
| 材料種類 | `metadata.material_type` | string | フィールド必須 | 可 | 30 |
| データ製作者 | `metadata.author` | string | フィールド必須 | 可 | 30 |
| 備考 | `metadata.notes` | string | フィールド必須 | 可 | 400 |

端末JSON読込時は、4値が文字列であることをブラウザで確認する。個別文字数上限は、読込後に再計算する通常フォームPOSTでも検証する。

### 3.3 切断条件

| 表示項目 | JSONフィールド | 型 | 必須 | 範囲 |
|---|---|---|---|---:|
| 新品母材長 | `cutting_conditions.new_stock_length_mm` | integer | 必須 | 1～6100 |
| 鋸刃厚 | `cutting_conditions.kerf_mm` | integer | 必須 | 0～100 |
| 左端捨て切り | `cutting_conditions.left_trim_mm` | integer | 必須 | 0～100 |

すべて単一値であり、`null`や空文字を受け付けない。フォーム初期値は鋸刃厚0mm、左端捨て切り10mmである。

### 3.4 必要部材

`required_parts`は1～20要素の配列である。各要素は次の2つの必須整数を持ち、`null`を受け付けない。

| JSONフィールド | 型 | 範囲 |
|---|---|---:|
| `length_mm` | integer | 1～6100 |
| `quantity` | integer | 1～500 |

同一寸法が複数行に存在する場合、計算時に本数を合算する。独立した合計必要本数1,000,000本制限はない。入力構造上の最大は20行 × 500本 = 10,000本である。

### 3.5 在庫新品材と在庫残材

`inventory`は在庫モードだけで使用する。

| 表示項目 | JSONフィールド | 型 | 必須 | 範囲・要素数 |
|---|---|---|---|---:|
| 在庫新品材本数 | `inventory.new_stock_quantity` | integer | 在庫モードで必須 | 0～500 |
| 在庫残材 | `inventory.remnants` | array | 在庫モードで必須 | 0～10要素 |
| 在庫残材寸法 | `inventory.remnants[].length_mm` | integer | 各要素で必須 | 1～6100 |
| 在庫残材本数 | `inventory.remnants[].quantity` | integer | 各要素で必須 | 1～500 |

`remnants`は空配列を許容する。配列要素や数値フィールドの`null`は受け付けない。

### 3.6 HTTPフォームとの対応

通常画面は `POST /` へHTMLフォームを送信する。HTTPフォーム値は文字列として受信し、サーバー側で整数と配列へ検証・変換してからPydanticモデルへ渡す。

| フォーム名 | 変換先 |
|---|---|
| `mode` | `mode` |
| `title` | `metadata.title` |
| `material_type` | `metadata.material_type` |
| `author` | `metadata.author` |
| `notes` | `metadata.notes` |
| `new_stock_length_mm` | `cutting_conditions.new_stock_length_mm` |
| `kerf_mm` | `cutting_conditions.kerf_mm` |
| `left_trim_mm` | `cutting_conditions.left_trim_mm` |
| 繰返し`part_length` / `part_quantity` | `required_parts[]` |
| `new_stock_quantity` | `inventory.new_stock_quantity` |
| 繰返し`remnant_length` / `remnant_quantity` | `inventory.remnants[]` |

寸法と本数が両方空の行は無視する。片方だけ入力された行は入力エラーとする。必要母材算出モードでは、画面上に残っている在庫フォーム値を計算入力へ含めない。

---

## 4. 管理番号と日時

### 4.1 現行管理番号

```text
NEST-YYYYMMDD-HHMMSS-XXXX
```

- 計算成功時に発行する。
- 日時部分は明示的に`Asia/Tokyo`へ変換して生成する。
- `XXXX`は`ABCDEFGHJKLMNPQRSTUVWXYZ23456789`から、暗号学的に安全なランダム選択で4文字を生成する。
- `I`、`O`、`0`、`1`など紛らわしい文字は使用しない。

JSONの`created_at`と`updated_at`は、UTCオフセット`+09:00`を持つISO 8601文字列である。新規計算時は両方を同じ計算成功時刻で発行する。

### 4.2 維持と再発行

- 入力を変更せず再計算する場合、有効な管理番号、`created_at`、`updated_at`を維持する。
- 入力変更後の再計算では、管理番号と両日時を新しく発行する。
- JSON読込直後は読み込んだ管理番号と日時を維持し、結果を無効な「再計算前」状態にする。入力を変更せず再計算すると識別情報を維持する。
- JSON・HTMLを出力するだけでは管理番号や日時を更新しない。同じ計算結果からの両出力は同じ識別情報を使用する。

画面表示用の「計算日時」はJSONの独立フィールドではない。保存JSONでは`created_at`と`updated_at`を識別日時として使用する。

### 4.3 旧形式互換

```text
NEST-YYYYMMDD-NNN
```

端末JSON読込では、`format_version: "1.0"`の旧管理番号形式も受け付ける。旧形式JSONを読み込み、入力を変更せず再計算した場合も、その管理番号と日時を維持する。新規発行には旧形式を使用しない。

---

## 5. JSON出力レコード

### 5.1 トップレベル

`POST /api/export/json`が返すJSONのトップレベルは次の7フィールドである。

| フィールド | 型 | 必須 | 内容 |
|---|---|---|---|
| `format_version` | string | 必須 | JSON形式バージョン。現行値`"1.0"` |
| `app_version` | string | 必須 | 生成アプリバージョン。現行値`"1.0.1"` |
| `management_number` | string | 必須 | 計算結果識別番号 |
| `created_at` | string | 必須 | `+09:00`付きISO 8601識別日時 |
| `updated_at` | string | 必須 | `+09:00`付きISO 8601識別日時 |
| `input` | object | 必須 | 正規化・検証済み計算入力と共通情報 |
| `calculation_result` | object | 必須 | 現行エンジンで再計算した結果 |

`status`、`result`、`calculation_datetime`は現行出力のトップレベルフィールドではない。

### 5.2 レコード例

```json
{
  "format_version": "1.0",
  "app_version": "1.0.1",
  "management_number": "NEST-20260805-103645-A7K2",
  "created_at": "2026-08-05T10:36:45+09:00",
  "updated_at": "2026-08-05T10:36:45+09:00",
  "input": {
    "mode": "required_stock",
    "cutting_conditions": {
      "new_stock_length_mm": 1030,
      "kerf_mm": 5,
      "left_trim_mm": 10
    },
    "required_parts": [
      {"length_mm": 500, "quantity": 2}
    ],
    "inventory": null,
    "metadata": {
      "title": "",
      "material_type": "",
      "author": "",
      "notes": ""
    }
  },
  "calculation_result": {
    "mode": "required_stock",
    "required_stock_quantity": 1,
    "additional_new_stock_required": 1,
    "existing_remnant_used": 0,
    "inventory_new_stock_used": 0,
    "patterns": [
      {
        "pattern_id": "P01",
        "usage_count": 1,
        "parts": [{"length_mm": 500, "quantity": 2}]
      }
    ],
    "stock_usage": [
      {
        "source_type": "additional_new_stock",
        "original_length_mm": 1030,
        "cuts": [500, 500],
        "pattern_id": "P01",
        "used_length_mm": 1025,
        "remaining_length_mm": 5,
        "remainder_class": "scrap"
      }
    ],
    "unused_inventory": [],
    "dimension_change_count": 0,
    "initial_setup_count": 1,
    "machine_setting_count": 1,
    "fulfillment": [
      {
        "length_mm": 500,
        "required_quantity": 2,
        "completed_from_inventory_quantity": 0,
        "completed_total_quantity": 2,
        "shortage_before_purchase_quantity": 2,
        "shortage_after_purchase_quantity": 0
      }
    ]
  }
}
```

---

## 6. 計算結果データ

### 6.1 calculation_result

| フィールド | 型 | 内容 |
|---|---|---|
| `mode` | string | `required_stock`または`inventory` |
| `required_stock_quantity` | integer | 実際に使用する材料の総本数 |
| `additional_new_stock_required` | integer | 購入新品材本数 |
| `existing_remnant_used` | integer | 使用した在庫残材本数 |
| `inventory_new_stock_used` | integer | 使用した在庫新品材本数 |
| `patterns` | array | 集約した切断パターン |
| `stock_usage` | array | 使用材料1本ごとの切出しと加工後状態 |
| `unused_inventory` | array | 未使用在庫と理由コード |
| `dimension_change_count` | integer | 寸法変更回数 |
| `initial_setup_count` | integer | 初回寸法設定回数 |
| `machine_setting_count` | integer | 初回設定と寸法変更の合計 |
| `fulfillment` | array | 寸法別の必要・完成・不足本数 |

### 6.2 patterns

```json
{
  "pattern_id": "P01",
  "usage_count": 2,
  "parts": [
    {"length_mm": 500, "quantity": 2}
  ]
}
```

`parts`はそのパターンを材料1本へ適用したときの寸法別切出し本数である。`usage_count`は同一パターンを使用する材料本数である。

### 6.3 stock_usage

```json
{
  "source_type": "additional_new_stock",
  "original_length_mm": 1030,
  "cuts": [500, 500],
  "pattern_id": "P01",
  "used_length_mm": 1025,
  "remaining_length_mm": 5,
  "remainder_class": "scrap"
}
```

`stock_usage`の`source_type`は次のいずれかである。

- `existing_remnant`：在庫残材
- `inventory_new_stock`：在庫新品材
- `additional_new_stock`：購入新品材

`remainder_class`は`used_up`、`scrap`、`remnant`のいずれかである。`cuts`が切出し部材の寸法配列、`remaining_length_mm`と`remainder_class`が使い切り・廃棄材・発生残材を表す。

### 6.4 unused_inventory

```json
{
  "source_type": "existing_remnant",
  "length_mm": 600,
  "quantity": 1,
  "reason_code": "NOT_SELECTED_BY_CANDIDATE_SELECTION"
}
```

未使用在庫の`source_type`は次のいずれかである。

- `existing_remnant`：在庫残材
- `held_new_stock`：在庫新品材の未使用分

`reason_code`は次のいずれかである。

- `NOT_NEEDED`
- `NO_REQUIRED_PART_FITS_AFTER_TRIM`
- `NOT_SELECTED_BY_CANDIDATE_SELECTION`

理由の判定規則は`CALCULATION_RULES.md`を参照する。

### 6.5 fulfillment

```json
{
  "length_mm": 500,
  "required_quantity": 2,
  "completed_from_inventory_quantity": 0,
  "completed_total_quantity": 2,
  "shortage_before_purchase_quantity": 2,
  "shortage_after_purchase_quantity": 0
}
```

購入新品材、在庫新品材、在庫残材、切出し部材、発生残材、廃棄材、使い切りは、独立した日本語名のトップレベル配列ではない。材料区分は`source_type`、切出し部材は`cuts`または`patterns[].parts`、加工後状態は`remaining_length_mm`と`remainder_class`から判別する。

切断手順もJSON内の独立配列ではない。HTMLとWeb表示では、`patterns`、`stock_usage`、切断条件から決定的に表示用データを生成する。

---

## 7. 端末JSON読込

### 7.1 読込経路

- 利用者が端末上のファイルを1つ選択する。
- ブラウザのFile APIで`file.text()`を実行し、ブラウザメモリ上で`JSON.parse`する。
- JSONファイル本体をHTTPでサーバーへ送信しない。
- 読込・検証・フォーム反映中に失敗した場合は、読込前の入力状態を維持する。

### 7.2 ファイル検証

| 項目 | 契約 |
|---|---|
| 拡張子 | 大文字・小文字を問わず`.json` |
| MIME type | 空値、`application/json`、`text/json`、または`+json`で終わる値 |
| ファイルサイズ | 5MiB以下 |
| JSONルート | 配列ではないオブジェクト |
| JSON最大深さ | 8 |
| `format_version` | `"1.0"` |
| `app_version` | string |
| 管理番号 | 現行形式または旧形式 |
| `created_at` / `updated_at` | 実在日時として解析可能な`+09:00`付き文字列 |
| 必要部材 | 1～20要素、寸法1～6100、本数1～500 |
| 在庫残材 | 0～10要素、寸法1～6100、本数1～500 |
| 在庫新品材 | 0～500 |
| 加工条件 | 母材長1～6100、鋸刃厚・左端捨て切り0～100 |

通常UIの行上限と端末JSON読込の配列上限は、V1.0.1では同じ20行・10行である。JSON数値はJavaScriptのsafe integerであることも必須とする。

### 7.3 読込後の扱い

- `input`を正規化してフォームへ反映する。
- 保存JSON内の`calculation_result`は存在とオブジェクト型だけを確認し、内容を画面結果として使用しない。
- 読込後の内部状態では`calculation_result`を空オブジェクトへ置き換える。
- JSON・HTML出力を無効にし、「JSON読込済み・再計算前」と表示する。
- 利用者が通常フォームPOSTで再計算すると、現行エンジンと現行入力制約で新しい結果を生成する。

---

## 8. JSON・HTML出力API

### 8.1 共通リクエスト

`POST /api/export/json`と`POST /api/export/html`は、`Content-Type: application/json`の次のリクエストを受け取る。

```json
{
  "input": {},
  "management_number": "NEST-20260805-103645-A7K2",
  "created_at": "2026-08-05T10:36:45+09:00",
  "updated_at": "2026-08-05T10:36:45+09:00"
}
```

`input`は第3章の構造である。サーバーはクライアントから計算結果を受け取らず、`mode`、`cutting_conditions`、`required_parts`、`inventory`をPydanticモデルで再検証し、現行エンジンで再計算して出力レコードを生成する。`metadata`は通常フォームで文字数検証済みの値を引き継ぐ。出力API単独では共通情報の文字数を再検証しないため、両APIは有効な画面計算結果から呼び出す契約である。

### 8.2 JSON出力

| 項目 | 契約 |
|---|---|
| メソッド・パス | `POST /api/export/json` |
| 成功ステータス | 200 |
| Content-Type | `application/json` |
| Content-Disposition | `attachment; filename="<management_number>.json"` |
| Cache-Control | `no-store` |
| 応答本文 | 第5・6章の完全な出力レコード |

### 8.3 HTML出力

| 項目 | 契約 |
|---|---|
| メソッド・パス | `POST /api/export/html` |
| 成功ステータス | 200 |
| Content-Type | `text/html; charset=utf-8`で始まる値 |
| Content-Disposition | `attachment; filename="<management_number>.html"` |
| Cache-Control | `no-store` |
| Pragma | `no-cache` |
| 応答本文 | UTF-8の自己完結した切断指示書HTML |

両APIは互いに独立しており、片方の出力を他方の前提にしない。レスポンスをメモリ上で生成し、サーバー上にファイルを作成しない。

productionではFastAPIのAPI文書`/docs`、`/redoc`、`/openapi.json`を公開しない。これは上記出力APIの利用可否とは別の公開設定である。

---

## 9. HTML出力契約

HTML出力は次を含む。

- 件名、材料種類、データ製作者、備考
- 管理番号と日付
- 計算モードと切断条件
- 必要部材と在庫情報
- 結果概要と寸法別充足状況
- パターン一覧
- 使用材料一覧と切出し部材
- 切断手順
- 発生残材、廃棄材、使い切り
- 未使用在庫と理由
- アプリバージョンとJSON形式バージョン

HTMLは次の出力特性を持つ。

- `<!DOCTYPE html>`と`<meta charset="UTF-8">`
- CSSを`<style>`内へ埋め込む
- 外部CDN・外部リソースへ依存しない
- Jinja2の自動エスケープにより利用者入力をHTMLエスケープする
- A4の`@page`、改ページ、印刷時の要素分断抑止を含む
- 600px以下の1カラム表示規則を含む
- `noindex, nofollow, noarchive`

HTMLはJSONと同じ完全な出力レコードと再計算結果から生成し、生成前後で入力レコードを変更しない。

---

## 10. エラー・検証契約

### 10.1 通常フォーム

- 範囲外数値、整数でない値、行数超過、必須行不足、片側だけの行、モードと在庫構造の不一致は計算しない。
- 通常の入力不正は`POST /`へHTTP 200の入力画面を返し、全体エラーと可能な範囲の入力欄別エラーを表示する。
- 入力値を可能な範囲で保持し、計算結果は表示しない。

### 10.2 出力API

JSON本文、必須キー、管理番号、日時、入力モデル、または計算が不正な場合、両出力APIはHTTP 400のJSONを返す。

```json
{
  "ok": false,
  "message": "処理できませんでした。入力内容を確認してください。"
}
```

エラー応答へ入力全文、内部例外、スタックトレースを含めない。

### 10.3 端末JSON読込

JSON構文不正、形式バージョン不一致、ファイルサイズ超過、深度超過、必須構造不足、行数・数値範囲外、管理番号・日時不正はブラウザ内で拒否し、利用者向けメッセージを表示する。ファイル本体をサーバーへ送信せず、読込前の状態を維持する。

### 10.4 HTTP本文サイズ

既定のHTTPリクエスト本文上限は64KiB（65,536バイト）である。上限超過はHTTP 413と次のJSONを返す。不正な`Content-Length`はHTTP 400とする。

```json
{"detail": "Request body too large"}
```

---

## 11. 保存・ログ方針

- JSONとHTMLは各出力リクエスト中にサーバーメモリ上で生成し、端末へ直接ダウンロードする。
- 入力内容、計算結果、JSON、HTML、一時ファイル、計算履歴をサーバーへ永続保存しない。
- `data/`などのサーバー保存先を使用しない。
- 保存済み一覧、上書き保存、管理番号検索、サーバーからの再ダウンロードを提供しない。
- 記録IDによるサーバー保存管理を行わない。管理番号は計算結果と端末出力を対応付ける識別情報である。
- 入力内容、管理情報、備考、計算結果、JSON全文、HTML全文をアプリケーションログへ記録しない。
- ページ内状態をデータベース、Cookie、LocalStorage、IndexedDBへ永続保存しない。

現行APIは`POST /api/export/json`と`POST /api/export/html`である。旧サーバー保存用の`/api/save`、`/api/records/*`、`/download/*`は現行機能ではない。

---

## 12. 関連文書

- 機能・利用上の正式仕様： [REQUIREMENTS.md](REQUIREMENTS.md)
- 計算・切断ルール： [CALCULATION_RULES.md](CALCULATION_RULES.md)
- 設計理由： [DECISIONS.md](DECISIONS.md)
- 計算例： [CALCULATION_EXAMPLES.md](CALCULATION_EXAMPLES.md)
- 試験結果： [TEST_RESULTS.md](TEST_RESULTS.md)
