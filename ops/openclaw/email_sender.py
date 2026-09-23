"""OpenClaw SMTP 发送器：为 FundAdvisor 日报提供硬性单日幂等保护。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo


CURRENT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = CURRENT_DIR / "smtp-config.json"
STATE_DIR = Path.home() / ".openclaw" / "state" / "fund-advisor-mail"
TEST_PLACEHOLDERS = {"test", "测试", "smtp test", "email test"}


class DuplicateDailyReportError(RuntimeError):
    """表示当天同一收件人的 FundAdvisor 日报已被认领或发送。"""


def _chmod_private(path: Path, mode: int) -> None:
    """仅在 POSIX 服务器上收紧权限，避免 Windows chmod 破坏测试目录。"""
    if os.name == "posix":
        os.chmod(path, mode)


def load_config() -> dict:
    """读取服务器本地 SMTP 配置，不向日志输出秘密。"""
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_body(body: str | None, body_file: str | None) -> str:
    """读取邮件正文并统一为字符串。"""
    if body_file:
        return Path(body_file).read_text(encoding="utf-8")
    return body or ""


def _reject_test_message(subject: str, body: str) -> None:
    """拒绝生产发送器中的纯测试占位邮件。"""
    normalized_subject = " ".join(subject.strip().lower().split())
    normalized_body = " ".join(body.strip().lower().split())
    if normalized_subject in TEST_PLACEHOLDERS or normalized_body in TEST_PLACEHOLDERS:
        raise ValueError("生产 SMTP 发送器禁止发送测试占位邮件")


def _is_fund_advisor_report(subject: str) -> bool:
    """仅识别 FundAdvisor 日报，避免影响其他 OpenClaw 邮件。"""
    return subject.strip().lower().startswith("fundadvisor")


def _claim_daily_report(to_email: str, now: datetime | None = None) -> Path:
    """原子认领当天日报发送权，防止并发或重复任务多发邮件。"""
    current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    recipient_hash = hashlib.sha256(to_email.strip().lower().encode("utf-8")).hexdigest()[:16]
    if os.name == "posix":
        STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    else:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
    _chmod_private(STATE_DIR, 0o700)
    claim_path = STATE_DIR / f"{current.date().isoformat()}-{recipient_hash}.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(claim_path, flags, 0o600)
    except FileExistsError as exc:
        raise DuplicateDailyReportError("当天 FundAdvisor 日报已经认领或发送") from exc

    payload = {
        "date": current.date().isoformat(),
        "status": "pending",
        "created_at": current.isoformat(),
    }
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return claim_path


def _mark_sent(claim_path: Path, now: datetime | None = None) -> None:
    """在成功投递后将匿名幂等记录标记为已发送。"""
    current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    payload = {
        "date": current.date().isoformat(),
        "status": "sent",
        "sent_at": current.isoformat(),
    }
    claim_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _chmod_private(claim_path, 0o600)


def send_email(
    to_email: str,
    subject: str,
    body: str | None,
    html: bool = False,
    body_file: str | None = None,
    attachments: list[str] | None = None,
) -> None:
    """发送邮件，并对 FundAdvisor 日报执行单日一次的硬性保护。"""
    body_content = _read_body(body, body_file)
    _reject_test_message(subject, body_content)
    claim_path = _claim_daily_report(to_email) if _is_fund_advisor_report(subject) else None
    smtp_sent = False

    try:
        config = load_config()
        message = MIMEMultipart()
        message["From"] = config["emailFrom"]
        message["To"] = to_email
        message["Subject"] = subject
        message.attach(MIMEText(body_content, "html" if html else "plain", "utf-8"))

        for file_path in attachments or []:
            with Path(file_path).open("rb") as attachment:
                mime_part = MIMEBase("application", "octet-stream")
                mime_part.set_payload(attachment.read())
            encoders.encode_base64(mime_part)
            mime_part.add_header(
                "Content-Disposition",
                f"attachment; filename={Path(file_path).name}",
            )
            message.attach(mime_part)

        smtp_factory = smtplib.SMTP_SSL if config.get("useTLS") else smtplib.SMTP
        with smtp_factory(config["server"], config["port"], timeout=30) as server:
            server.login(config["username"], config["password"])
            server.send_message(message)
            smtp_sent = True

        if claim_path:
            _mark_sent(claim_path)
    except Exception:
        # SMTP 明确失败时撤销认领，允许人工确认后重试；进程异常退出则保留 pending，优先防重复。
        if claim_path and claim_path.exists() and not smtp_sent:
            claim_path.unlink()
        raise


def main() -> int:
    """解析命令行参数并执行一次受控发送。"""
    parser = argparse.ArgumentParser(description="通过 SMTP 发送受控邮件")
    parser.add_argument("--to", required=True, help="收件人")
    parser.add_argument("--subject", required=True, help="邮件主题")
    parser.add_argument("--body", help="邮件正文")
    parser.add_argument("--body-file", help="HTML 或文本正文文件")
    parser.add_argument("--html", action="store_true", help="按 HTML 发送")
    parser.add_argument("--attachments", nargs="*", help="附件路径")
    args = parser.parse_args()

    if not args.body and not args.body_file:
        parser.error("必须提供 --body 或 --body-file")

    try:
        send_email(
            to_email=args.to,
            subject=args.subject,
            body=args.body,
            body_file=args.body_file,
            html=args.html,
            attachments=args.attachments or [],
        )
    except DuplicateDailyReportError as exc:
        print(f"SKIPPED_DUPLICATE: {exc}")
        return 3
    except ValueError as exc:
        print(f"BLOCKED_MESSAGE: {exc}")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
