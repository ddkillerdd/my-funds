"""Import service - handles Excel upload, parse, and merge into database."""

import shutil
import tempfile
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.models.fund import Fund
from backend.models.holding import FundHolding
from backend.models.holding_change import HoldingChange
from backend.models.import_record import ImportRecord
from backend.schemas.import_result import ImportResult, ImportHistoryItem
from backend.schemas.holding_change import HoldingChangeResponse
from backend.services.excel_parser import (
    parse_excel,
    compute_file_hash,
    ExcelParseError,
    BatchValidationError,
    _deduplicate_holdings,
)
from backend.services.holding_service import build_holding_change

UPLOAD_DIR = Path("data/uploads")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_ZIP_MEMBERS = 100
MAX_ZIP_MEMBER_BYTES = 20 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 100 * 1024 * 1024


class ImportService:
    def __init__(self, db: Session):
        self.db = db

    def _detect_file_type(self, filename: str) -> str:
        """Detect file type from extension."""
        ext = Path(filename).suffix.lower()
        if ext == ".zip":
            return "zip"
        elif ext in (".xlsx", ".xls"):
            return "excel"
        else:
            return "unknown"

    def _safe_filename(self, filename: str) -> str:
        """限制上传文件名，避免路径穿越和空文件名。"""
        normalized = str(filename or "").replace("\\", "/")
        if "\x00" in normalized:
            raise ValueError("上传文件名非法")
        safe_name = Path(normalized).name
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("上传文件名非法")
        return safe_name

    async def _save_upload(self, file: UploadFile, target: Path) -> None:
        """以大小上限保存上传文件，避免一次性读入内存。"""
        total = 0
        with open(target, "wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise ValueError("上传文件超过 20MB 限制")
                output.write(chunk)
        if total == 0:
            raise ValueError("上传文件不能为空")

    def _new_upload_path(self, safe_filename: str) -> Path:
        """为上传生成不可预测的临时存储名。"""
        return UPLOAD_DIR / f"{uuid4().hex}_{safe_filename}"

    def _import_parsed_batch(
        self,
        file_name: str,
        file_hash: str,
        holdings,
        errors: list[dict],
        data_date: Optional[date],
    ) -> ImportResult:
        """在解析和全局校验完成后，以一次事务合并整批快照。"""
        if data_date is None or not holdings:
            message = "未找到有效持仓记录或无法确定文件业务日期"
            try:
                record = ImportRecord(file_name=file_name, file_hash=file_hash, status="error", error_message=message)
                self.db.add(record)
                self.db.flush()
                self.db.commit()
                return ImportResult(import_id=record.id, file_name=file_name, status="error", error_message=message)
            except Exception:
                self.db.rollback()
                raise
        record = ImportRecord(
            file_name=file_name, file_hash=file_hash, total_rows=len(holdings),
            error_rows=len(errors), data_date=data_date,
        )
        try:
            self.db.add(record)
            self.db.flush()
            new_count, updated_count, removed_count, changes = self._merge_holdings(
                holdings, record.id, data_date, allow_clear=not errors
            )
            record.new_holdings = new_count
            record.updated_holdings = updated_count
            record.removed_holdings = removed_count
            record.status = "success" if not errors else "partial"
            record.error_message = "; ".join(
                f"{error.get('sheet', '')}行{error.get('row', '')}: {error['message']}".strip()
                for error in errors[:10]
            ) or None
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return ImportResult(
            import_id=record.id, file_name=file_name, total_rows=record.total_rows,
            new_holdings=new_count, updated_holdings=updated_count,
            removed_holdings=removed_count, error_rows=len(errors),
            data_date=data_date, status=record.status,
            error_message=record.error_message,
            changes=[HoldingChangeResponse.model_validate(change) for change in changes],
        )

    async def import_file(self, file: UploadFile) -> ImportResult:
        """Import file - auto-detects type (Excel or ZIP)."""
        try:
            safe_filename = self._safe_filename(file.filename)
        except ValueError as exc:
            return ImportResult(import_id=0, file_name="upload", status="error", error_message=str(exc))
        file_type = self._detect_file_type(safe_filename)

        if file_type == "zip":
            return await self.import_zip(file)
        elif file_type == "excel":
            return await self.import_excel(file)
        else:
            return ImportResult(
                import_id=0,
                file_name=safe_filename,
                status="error",
                error_message="不支持的文件类型，请上传 .xlsx 或 .zip 文件",
            )

    async def import_excel(self, file: UploadFile) -> ImportResult:
        """保存、解析并原子合并一个 Excel 快照。"""
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        path = None
        try:
            safe_filename = self._safe_filename(file.filename)
            path = self._new_upload_path(safe_filename)
            await self._save_upload(file, path)
            file_hash = compute_file_hash(path)
            existing = self.db.execute(
                select(ImportRecord).where(ImportRecord.file_hash == file_hash)
            ).scalar_one_or_none()
            if existing:
                return self._duplicate_result(existing, safe_filename)
            holdings, errors, data_date = parse_excel(path)
            return self._import_parsed_batch(safe_filename, file_hash, holdings, errors, data_date)
        except (ValueError, ExcelParseError) as exc:
            return ImportResult(import_id=0, file_name=locals().get("safe_filename", "upload"), status="error", error_message=str(exc))
        finally:
            if path is not None and path.parent == UPLOAD_DIR:
                path.unlink(missing_ok=True)

    def _duplicate_result(self, record: ImportRecord, file_name: str) -> ImportResult:
        """构造重复文件结果，不重复写入持仓。"""
        return ImportResult(
            import_id=record.id, file_name=file_name, total_rows=record.total_rows,
            new_holdings=record.new_holdings, updated_holdings=record.updated_holdings,
            removed_holdings=record.removed_holdings, error_rows=record.error_rows,
            data_date=record.data_date, status="duplicate", error_message="该文件已导入过",
        )

    async def import_zip(self, file: UploadFile) -> ImportResult:
        """安全解压并一次性合并 ZIP 内的全部 xlsx 快照。"""
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = None
        temp_dir = None
        try:
            safe_filename = self._safe_filename(file.filename)
            zip_path = self._new_upload_path(safe_filename)
            temp_dir = Path(tempfile.mkdtemp(prefix="import_", dir=UPLOAD_DIR))
            await self._save_upload(file, zip_path)
            zip_hash = compute_file_hash(zip_path)
            existing = self.db.execute(
                select(ImportRecord).where(ImportRecord.file_hash == zip_hash)
            ).scalar_one_or_none()
            if existing:
                return self._duplicate_result(existing, safe_filename)
            holdings = []
            errors: list[dict] = []
            data_dates: set[date] = set()
            actual_total_size = 0
            with zipfile.ZipFile(zip_path, "r") as archive:
                members = archive.infolist()
                self._validate_zip_members(members)
                files = []
                for index, member in enumerate(members):
                    if member.is_dir():
                        continue
                    if Path(member.filename).suffix.lower() != ".xlsx":
                        continue
                    target = temp_dir / f"member_{index:03d}.xlsx"
                    actual_total_size += self._copy_zip_member(archive, member, target)
                    if actual_total_size > MAX_ZIP_TOTAL_BYTES:
                        raise ValueError("ZIP 实际解压总量超过限制")
                    files.append((member.filename.replace("\\", "/").casefold(), target))
                if not files:
                    raise ExcelParseError("ZIP 文件中未找到 .xlsx 业务文件")
                for member_name, path in sorted(files, key=lambda item: item[0]):
                    try:
                        parsed, file_errors, data_date = parse_excel(path)
                        holdings.extend(parsed)
                        errors.extend({**error, "file": member_name} for error in file_errors)
                        if data_date is not None:
                            data_dates.add(data_date)
                    except BatchValidationError:
                        raise
                    except ExcelParseError as exc:
                        errors.append({"file": member_name, "row": "", "message": str(exc)})
                if len(data_dates) > 1:
                    raise ExcelParseError("ZIP 内文件包含多个业务日期，拒绝合并")
                if not holdings:
                    raise ExcelParseError("ZIP 内没有有效持仓记录")
                holdings = _deduplicate_holdings(holdings)
                return self._import_parsed_batch(
                    safe_filename, zip_hash, holdings, errors, next(iter(data_dates), None)
                )
        except (ValueError, ExcelParseError, zipfile.BadZipFile) as exc:
            return ImportResult(import_id=0, file_name=locals().get("safe_filename", "upload"), status="error", error_message=str(exc))
        finally:
            if temp_dir is not None and temp_dir.parent == UPLOAD_DIR:
                shutil.rmtree(temp_dir, ignore_errors=True)
            if zip_path is not None and zip_path.parent == UPLOAD_DIR:
                zip_path.unlink(missing_ok=True)

    def _validate_zip_members(self, members) -> None:
        """校验 ZIP 成员路径、类型、加密标志和解压大小。"""
        if len(members) > MAX_ZIP_MEMBERS:
            raise ValueError("ZIP 文件成员数超过限制")
        total_size = 0
        normalized_names: set[str] = set()
        for member in members:
            name = member.filename
            normalized = name.replace("\\", "/")
            path = Path(normalized)
            mode = (member.external_attr >> 16) & 0o170000
            has_drive = bool(path.parts and ":" in path.parts[0])
            if "\x00" in name or path.is_absolute() or has_drive:
                raise ValueError("ZIP 文件包含非法路径")
            if any(part in {"..", ""} for part in path.parts) or name.startswith(("/", "\\", "//")):
                raise ValueError("ZIP 文件包含非法路径")
            key = normalized.casefold()
            if key in normalized_names:
                raise ValueError("ZIP 文件包含重复成员路径")
            normalized_names.add(key)
            if member.flag_bits & 0x1:
                raise ValueError("不支持加密 ZIP 成员")
            if Path(name).suffix.lower() == ".xls":
                raise ExcelParseError("ZIP 内不支持 .xls 格式")
            if mode == 0o120000:
                raise ValueError("不支持 ZIP 符号链接")
            if not member.is_dir() and mode not in (0, 0o100000):
                raise ValueError("ZIP 成员不是普通文件")
            if member.file_size > MAX_ZIP_MEMBER_BYTES:
                raise ValueError("ZIP 单个文件超过限制")
            total_size += member.file_size
        if total_size > MAX_ZIP_TOTAL_BYTES:
            raise ValueError("ZIP 解压总量超过限制")

    def _copy_zip_member(self, archive, member, target: Path) -> int:
        """流式复制 ZIP 成员并限制实际解压字节数。"""
        size = 0
        with archive.open(member, "r") as source, open(target, "wb") as output:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ZIP_MEMBER_BYTES:
                    raise ValueError("ZIP 成员实际解压大小超过限制")
                output.write(chunk)
        return size

    def _merge_holdings(
        self, holdings, import_id: int, business_date: date, allow_clear: bool = True
    ) -> tuple[int, int, int, list[HoldingChange]]:
        """Merge parsed holdings into database.

        Strategy:
        - Existing key match -> update shares/nav/market_value
        - New key -> insert new holding + ensure fund exists
        - DB holdings not in Excel -> mark status=0 (cleared)

        Returns (new_count, updated_count, removed_count, changes).
        """
        new_count = 0
        updated_count = 0
        changes: list[HoldingChange] = []

        # Build set of keys from Excel
        excel_keys = set()
        for h in holdings:
            excel_keys.add(h.unique_key)

        # Process each holding
        for h in holdings:
            existing = self.db.execute(
                select(FundHolding).where(
                    FundHolding.fund_code == h.fund_code,
                    FundHolding.platform == h.platform,
                    FundHolding.fund_account == h.fund_account,
                    FundHolding.trade_account == h.trade_account,
                )
            ).scalar_one_or_none()

            if existing:
                old_shares = existing.shares or Decimal("0")
                old_mv = existing.market_value or Decimal("0")
                new_shares = h.shares
                new_mv = h.market_value or Decimal("0")
                was_cleared = existing.status == 0

                # Update existing holding
                existing.shares = h.shares
                existing.share_date = h.share_date
                existing.nav_on_import = h.nav
                existing.nav_date = h.nav_date
                existing.market_value = h.market_value
                existing.fund_name = h.fund_name
                existing.management_company = h.management_company
                existing.dividend_mode = h.dividend_mode
                existing.last_import_id = import_id
                existing.source_type = "file"
                existing.status = 1  # Re-activate if was cleared
                # Do NOT overwrite cost_nav on update
                updated_count += 1

                # Determine change type
                if was_cleared:
                    change_type = "new"
                    old_shares = Decimal("0")
                    old_mv = Decimal("0")
                elif new_shares > old_shares:
                    change_type = "increase"
                elif new_shares < old_shares:
                    change_type = "decrease"
                else:
                    change_type = None  # No change in shares

                if change_type:
                    change = build_holding_change(
                        import_id=import_id, holding_id=existing.id,
                        fund_code=h.fund_code, fund_name=h.fund_name,
                        platform=h.platform, change_type=change_type,
                        shares_before=old_shares, shares_after=new_shares,
                        shares_delta=new_shares - old_shares, nav_at_change=h.nav,
                        mv_before=old_mv, mv_after=new_mv,
                        business_date=business_date,
                        source_type="file",
                    )
                    self.db.add(change)
                    changes.append(change)
            else:
                # Insert new holding
                new_holding = FundHolding(
                    fund_code=h.fund_code,
                    fund_name=h.fund_name,
                    share_type=h.share_type,
                    management_company=h.management_company,
                    platform=h.platform,
                    fund_account=h.fund_account,
                    trade_account=h.trade_account,
                    shares=h.shares,
                    share_date=h.share_date,
                    nav_on_import=h.nav,
                    nav_date=h.nav_date,
                    market_value=h.market_value,
                    currency=h.currency,
                    dividend_mode=h.dividend_mode,
                    last_import_id=import_id,
                    source_type="file",
                    status=1,
                    cost_nav=h.nav,  # Set cost_nav on first import
                )
                self.db.add(new_holding)
                self.db.flush()  # get new_holding.id
                new_count += 1

                change = build_holding_change(
                    import_id=import_id, holding_id=new_holding.id,
                    fund_code=h.fund_code, fund_name=h.fund_name,
                    platform=h.platform, change_type="new",
                    shares_before=Decimal("0"), shares_after=h.shares,
                    shares_delta=h.shares, nav_at_change=h.nav,
                    mv_before=Decimal("0"), mv_after=h.market_value or Decimal("0"),
                    business_date=business_date,
                    source_type="file",
                )
                self.db.add(change)
                changes.append(change)

            # Ensure fund exists in funds table
            self._ensure_fund(h)

        # Mark holdings not in Excel as cleared (status=0)
        if not allow_clear:
            self.db.flush()
            return new_count, updated_count, 0, changes

        all_active = self.db.execute(
            select(FundHolding).where(FundHolding.status == 1)
        ).scalars().all()

        removed_count = 0
        for holding in all_active:
            # 文件导入只能清理自己历史写入的持仓，不能清除手工或快捷来源。
            if holding.source_type != "file" or holding.last_import_id is None:
                continue
            key = (
                holding.fund_code,
                holding.platform,
                holding.fund_account,
                holding.trade_account,
            )
            if key not in excel_keys:
                old_shares = holding.shares or Decimal("0")
                old_mv = holding.market_value or Decimal("0")
                holding.status = 0
                holding.shares = Decimal("0")  # zero out shares on clear
                removed_count += 1

                change = build_holding_change(
                    import_id=import_id, holding_id=holding.id,
                    fund_code=holding.fund_code, fund_name=holding.fund_name,
                    platform=holding.platform, change_type="clear",
                    shares_before=old_shares, shares_after=Decimal("0"),
                    shares_delta=-old_shares, nav_at_change=holding.nav_on_import,
                    mv_before=old_mv, mv_after=Decimal("0"),
                    business_date=business_date,
                    source_type="file",
                )
                self.db.add(change)
                changes.append(change)

        self.db.flush()
        return new_count, updated_count, removed_count, changes

    def _ensure_fund(self, h) -> None:
        """Ensure fund exists in funds table, create if not.

        fund_type is left NULL for new funds; it will be backfilled
        by _backfill_fund_types() during the next NAV refresh.
        """
        existing = self.db.execute(
            select(Fund).where(Fund.fund_code == h.fund_code)
        ).scalar_one_or_none()

        if not existing:
            fund = Fund(
                fund_code=h.fund_code,
                fund_name=h.fund_name,
                management_company=h.management_company,
                latest_nav=h.nav,
                latest_nav_date=h.nav_date,
            )
            self.db.add(fund)
            self.db.flush()

    def get_import_history(self) -> list[ImportHistoryItem]:
        """Get all import records, newest first."""
        records = self.db.execute(
            select(ImportRecord).order_by(ImportRecord.created_at.desc())
        ).scalars().all()
        return [ImportHistoryItem.model_validate(r) for r in records]

    def get_import_changes(self, import_id: int) -> list[HoldingChangeResponse]:
        """Get holding changes for a specific import."""
        changes = self.db.execute(
            select(HoldingChange)
            .where(HoldingChange.import_id == import_id)
            .order_by(HoldingChange.change_type, HoldingChange.fund_code)
        ).scalars().all()
        return [HoldingChangeResponse.model_validate(c) for c in changes]
