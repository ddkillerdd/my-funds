"""OpenClaw FundAdvisor 邮件发送器的离线合成测试。"""

from __future__ import annotations

import importlib.util
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


MODULE_PATH = Path(__file__).parents[1] / "openclaw" / "email_sender.py"
SPEC = importlib.util.spec_from_file_location("openclaw_email_sender", MODULE_PATH)
email_sender = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(email_sender)


@pytest.fixture
def local_state_dir():
    """在仓库内创建独立测试目录，绕过本机 pytest 临时目录权限异常。"""
    root = MODULE_PATH.parents[2] / "mailguard-test-root"
    root.mkdir(exist_ok=True)
    path = root / f"case-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            root.rmdir()
        except OSError:
            pass


def test_rejects_test_placeholder():
    """断言纯 test 正文无法进入生产 SMTP。"""
    with pytest.raises(ValueError, match="禁止发送测试"):
        email_sender._reject_test_message("任意主题", "TEST")


def test_daily_claim_is_atomic_and_anonymous(local_state_dir, monkeypatch):
    """断言同日同收件人只能认领一次，且文件名不暴露邮箱。"""
    monkeypatch.setattr(email_sender, "STATE_DIR", local_state_dir / "state")
    now = datetime(2026, 9, 23, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    claim = email_sender._claim_daily_report("holder@example.invalid", now=now)

    assert claim.exists()
    assert "holder" not in claim.name
    assert "example" not in claim.name
    with pytest.raises(email_sender.DuplicateDailyReportError):
        email_sender._claim_daily_report("holder@example.invalid", now=now)


def test_non_fund_advisor_mail_does_not_create_claim(local_state_dir, monkeypatch):
    """断言普通 OpenClaw 邮件不受 FundAdvisor 日报锁影响。"""
    calls = []

    class FakeSMTP:
        """模拟 SMTP，禁止真实网络。"""

        def __init__(self, *args, **kwargs):
            calls.append("connect")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, *args):
            calls.append("login")

        def send_message(self, message):
            calls.append(message["Subject"])

    monkeypatch.setattr(email_sender, "STATE_DIR", local_state_dir / "state")
    monkeypatch.setattr(
        email_sender,
        "load_config",
        lambda: {
            "server": "127.0.0.1",
            "port": 1,
            "username": "disabled",
            "password": "disabled",
            "emailFrom": "disabled@example.invalid",
            "useTLS": True,
        },
    )
    monkeypatch.setattr(email_sender.smtplib, "SMTP_SSL", FakeSMTP)

    email_sender.send_email("holder@example.invalid", "普通通知", "正文")

    assert calls[-1] == "普通通知"
    assert not (local_state_dir / "state").exists()


def test_fund_advisor_report_sends_once(local_state_dir, monkeypatch):
    """断言 FundAdvisor 日报成功后同日第二次会在 SMTP 前被阻止。"""
    send_count = 0

    class FakeSMTP:
        """模拟 SMTP 并记录发送次数。"""

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, *args):
            pass

        def send_message(self, message):
            nonlocal send_count
            send_count += 1

    monkeypatch.setattr(email_sender, "STATE_DIR", local_state_dir / "state")
    monkeypatch.setattr(
        email_sender,
        "load_config",
        lambda: {
            "server": "127.0.0.1",
            "port": 1,
            "username": "disabled",
            "password": "disabled",
            "emailFrom": "disabled@example.invalid",
            "useTLS": True,
        },
    )
    monkeypatch.setattr(email_sender.smtplib, "SMTP_SSL", FakeSMTP)

    email_sender.send_email(
        "holder@example.invalid",
        "FundAdvisor 每日报告 - 2026-09-23",
        "正式报告",
        html=True,
    )

    with pytest.raises(email_sender.DuplicateDailyReportError):
        email_sender.send_email(
            "holder@example.invalid",
            "FundAdvisor 每日报告 - 2026-09-23",
            "正式报告",
            html=True,
        )
    assert send_count == 1


def test_sent_mail_keeps_claim_when_final_mark_fails(local_state_dir, monkeypatch):
    """断言 SMTP 已成功后即使最终标记异常也保留认领，优先避免重复邮件。"""

    class FakeSMTP:
        """模拟已成功投递的 SMTP。"""

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, *args):
            pass

        def send_message(self, message):
            pass

    monkeypatch.setattr(email_sender, "STATE_DIR", local_state_dir / "state")
    monkeypatch.setattr(
        email_sender,
        "load_config",
        lambda: {
            "server": "127.0.0.1",
            "port": 1,
            "username": "disabled",
            "password": "disabled",
            "emailFrom": "disabled@example.invalid",
            "useTLS": True,
        },
    )
    monkeypatch.setattr(email_sender.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(
        email_sender,
        "_mark_sent",
        lambda claim_path: (_ for _ in ()).throw(OSError("synthetic mark failure")),
    )

    with pytest.raises(OSError, match="synthetic mark failure"):
        email_sender.send_email(
            "holder@example.invalid",
            "FundAdvisor 每日报告 - 2026-09-23",
            "正式报告",
            html=True,
        )

    assert len(list((local_state_dir / "state").glob("*.json"))) == 1
