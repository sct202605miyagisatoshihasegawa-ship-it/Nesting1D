import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

FORMAT_VERSION = "1.0"
APP_VERSION = "0.1.0"
TOKYO = ZoneInfo("Asia/Tokyo")
NUMBER_PATTERN = re.compile(r"^NEST-(\d{8})-(\d{3})$")

class StorageError(Exception):
    pass

class RecordExistsError(StorageError):
    pass

class UnsupportedFormatError(StorageError):
    pass

def tokyo_now() -> datetime:
    return datetime.now(TOKYO)

class RecordStorage:
    def __init__(self, data_dir: Path, clock: Callable[[], datetime] = tokyo_now):
        self.data_dir = data_dir.resolve()
        self.clock = clock

    def _path(self, number: str, suffix: str) -> Path:
        if not NUMBER_PATTERN.fullmatch(number):
            raise StorageError("管理番号の形式が正しくありません。")
        path = (self.data_dir / f"{number}{suffix}").resolve()
        if path.parent != self.data_dir:
            raise StorageError("保存先が許可された範囲外です。")
        return path

    def next_number(self, now: datetime | None = None) -> str:
        current = (now or self.clock()).astimezone(TOKYO)
        date_text = current.strftime("%Y%m%d")
        maximum = 0
        if self.data_dir.exists():
            for path in self.data_dir.glob(f"NEST-{date_text}-*.json"):
                match = NUMBER_PATTERN.fullmatch(path.stem)
                if match:
                    maximum = max(maximum, int(match.group(2)))
        if maximum >= 999:
            raise StorageError("本日の管理番号が上限に達しました。")
        return f"NEST-{date_text}-{maximum + 1:03d}"

    def save_new(self, builder: Callable[[str, datetime], tuple[dict, str]]) -> dict:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for _ in range(999):
            now = self.clock().astimezone(TOKYO)
            number = self.next_number(now)
            json_path = self._path(number, ".json")
            html_path = self._path(number, ".html")
            lock_path = self._path(number, ".lock")
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
            except FileExistsError:
                continue
            try:
                if json_path.exists() or html_path.exists():
                    continue
                record, html = builder(number, now)
                self._replace_pair(json_path, html_path, record, html, overwrite=False)
                return record
            finally:
                lock_path.unlink(missing_ok=True)
        raise StorageError("管理番号を採番できませんでした。再度お試しください。")

    def overwrite(self, record: dict, html: str) -> dict:
        number = str(record.get("management_number", ""))
        json_path = self._path(number, ".json")
        html_path = self._path(number, ".html")
        if not json_path.exists():
            raise StorageError("上書き対象の保存データが見つかりません。")
        self._replace_pair(json_path, html_path, record, html, overwrite=True)
        return record

    def _replace_pair(self, json_path: Path, html_path: Path, record: dict, html: str, overwrite: bool) -> None:
        if not overwrite and (json_path.exists() or html_path.exists()):
            raise RecordExistsError("同じ管理番号のファイルが既に存在します。")
        contents = (
            (json_path, json.dumps(record, ensure_ascii=False, indent=2) + "\n"),
            (html_path, html),
        )
        temporary_paths: list[Path] = []
        backups: dict[Path, bytes | None] = {}
        try:
            for destination, content in contents:
                backups[destination] = destination.read_bytes() if destination.exists() else None
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", newline="\n", dir=self.data_dir,
                    prefix=f".{destination.name}.", suffix=".tmp", delete=False,
                ) as temporary:
                    temporary.write(content)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temporary_paths.append(Path(temporary.name))
            os.replace(temporary_paths[0], json_path)
            os.replace(temporary_paths[1], html_path)
        except Exception as exc:
            self._restore(backups)
            raise StorageError("保存に失敗しました。既存データは変更されていません。") from exc
        finally:
            for path in temporary_paths:
                path.unlink(missing_ok=True)

    def _restore(self, backups: dict[Path, bytes | None]) -> None:
        for destination, content in backups.items():
            if content is None:
                destination.unlink(missing_ok=True)
                continue
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.data_dir, prefix=".restore.", delete=False) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, destination)

    def load(self, number: str) -> dict:
        try:
            record = json.loads(self._path(number, ".json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StorageError("JSONを読み込めませんでした。ファイル内容を確認してください。") from exc
        return validate_record(record)

    def list_records(self) -> list[str]:
        if not self.data_dir.exists():
            return []
        return sorted((path.stem for path in self.data_dir.glob("NEST-*.json") if NUMBER_PATTERN.fullmatch(path.stem)), reverse=True)

def validate_record(record: object) -> dict:
    if not isinstance(record, dict):
        raise StorageError("JSONのルートはオブジェクトである必要があります。")
    version = record.get("format_version")
    if version != FORMAT_VERSION:
        raise UnsupportedFormatError(f"このデータ形式（{version}）には対応していません。対応形式は{FORMAT_VERSION}です。")
    required = {"app_version", "management_number", "created_at", "updated_at", "input", "calculation_result"}
    if not required.issubset(record):
        raise StorageError("保存JSONに必要な項目がありません。")
    if not NUMBER_PATTERN.fullmatch(str(record["management_number"])):
        raise StorageError("保存JSONの管理番号が正しくありません。")
    if not isinstance(record["input"], dict) or not isinstance(record["calculation_result"], dict):
        raise StorageError("保存JSONの入力または計算結果が正しくありません。")
    return record
