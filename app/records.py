# Nesting1D - レコード識別情報と検証
# 役割: バージョン、管理番号、日時、および出力レコードの互換性を管理する。
# 更新日: 2026-08-10

import re
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


FORMAT_VERSION = "1.0"
APP_VERSION = "1.0.1"
TOKYO = ZoneInfo("Asia/Tokyo")
MANAGEMENT_NUMBER_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LEGACY_MANAGEMENT_NUMBER_PATTERN = re.compile(r"^NEST-(\d{8})-(\d{3})$")
CURRENT_MANAGEMENT_NUMBER_PATTERN = re.compile(
    rf"^NEST-(\d{{8}})-(\d{{6}})-([{MANAGEMENT_NUMBER_ALPHABET}]{{4}})$"
)


class RecordError(Exception):
    pass


class UnsupportedFormatError(RecordError):
    pass


def tokyo_now() -> datetime:
    return datetime.now(TOKYO)


def generate_management_number(now: datetime | None = None) -> str:
    current = (now or tokyo_now()).astimezone(TOKYO)
    random_text = "".join(secrets.choice(MANAGEMENT_NUMBER_ALPHABET) for _ in range(4))
    return f"NEST-{current:%Y%m%d-%H%M%S}-{random_text}"


def is_valid_management_number(number: str) -> bool:
    return bool(
        LEGACY_MANAGEMENT_NUMBER_PATTERN.fullmatch(number)
        or CURRENT_MANAGEMENT_NUMBER_PATTERN.fullmatch(number)
    )


def is_valid_tokyo_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(hours=9)


def validate_record(record: object) -> dict:
    if not isinstance(record, dict):
        raise RecordError("JSONのルートはオブジェクトである必要があります。")
    version = record.get("format_version")
    if version != FORMAT_VERSION:
        raise UnsupportedFormatError(
            f"このデータ形式（{version}）には対応していません。対応形式は{FORMAT_VERSION}です。"
        )
    required = {
        "app_version",
        "management_number",
        "created_at",
        "updated_at",
        "input",
        "calculation_result",
    }
    if not required.issubset(record):
        raise RecordError("JSONに必要な項目がありません。")
    if not is_valid_management_number(str(record["management_number"])):
        raise RecordError("JSONの管理番号が正しくありません。")
    if not is_valid_tokyo_timestamp(record["created_at"]) or not is_valid_tokyo_timestamp(record["updated_at"]):
        raise RecordError("JSONの日時が正しくありません。")
    if not isinstance(record["input"], dict) or not isinstance(record["calculation_result"], dict):
        raise RecordError("JSONの入力または計算結果が正しくありません。")
    return record
