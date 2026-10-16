"""只查询当前四只基金的公开销售页面，永不伪装成账户资格或账户剩余额度。"""
from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
import re

import httpx

from backend.services.purchase_channel_service import SHANGHAI, decimal_value


SUPPORTED_CODES = frozenset({"013308", "022430", "270042", "018044"})
PUBLIC_URL = "https://fundf10.eastmoney.com/jjfl_{code}.html"
MAX_BYTES = 500000


class _TableReader(HTMLParser):
    """按节标题提取可见表格单元格，排除划掉的原费率和脚本内容。"""

    def __init__(self):
        """初始化纯内存解析状态。"""
        super().__init__(convert_charrefs=True)
        self.section = ""
        self.heading = None
        self.cell = None
        self.row = None
        self.hidden = 0
        self.rows = []
        self.headings = []

    def handle_starttag(self, tag, attrs):
        """开始收集标题或表格单元格，并跳过删除线和脚本。"""
        if tag in {"script", "style", "s", "strike", "del"}:
            self.hidden += 1
        if tag in {"h1", "h2", "h3", "h4"}:
            self.heading = []
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        """仅累积可见文字，不解释页面脚本或文档中的指令。"""
        if not self.hidden:
            if self.heading is not None:
                self.heading.append(data)
            if self.cell is not None:
                self.cell.append(data)

    def handle_endtag(self, tag):
        """将完整标题和行写入解析结果。"""
        if tag in {"script", "style", "s", "strike", "del"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"h1", "h2", "h3", "h4"} and self.heading is not None:
            self.section = "".join(self.heading).strip()
            self.headings.append(self.section)
            self.heading = None
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(re.sub(r"\s+", "", "".join(self.cell)))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append((self.section, self.row))
            self.row = None


def _single_field(rows, label):
    """只接受一致的字段值，页面出现互相冲突的值则返回未知。"""
    values = {cells[i + 1] for _, cells in rows for i, cell in enumerate(cells[:-1]) if cell == label}
    return values.pop() if len(values) == 1 else None


def _money_text(text):
    """仅识别明确的人民币金额，未知和无限额不转换成虚构账户额度。"""
    match = re.fullmatch(r"([0-9,]+(?:\.[0-9]+)?)(万)?元", text or "")
    if not match:
        return None
    value = decimal_value(match.group(1).replace(",", ""))
    return float(value * (10000 if match.group(2) else 1))


def parse_public_purchase_page(code, markup, *, now=None):
    """提取小额申购公开费率；不生成可执行金额、不推断私有优惠。"""
    if not re.fullmatch(r"\d{6}", str(code)):
        raise ValueError("基金代码必须为六位数字")
    clock = now or datetime.now(SHANGHAI)
    result = {
        "fund_code": code, "platform": "天天基金", "source": PUBLIC_URL.format(code=code),
        "observed_at": clock.isoformat(), "evidence_scope": "public_only",
        "account_eligible": None, "daily_remaining_rmb": None,
        "purchase_status": "unknown", "subscription_fee_rate_pct": None,
        "min_purchase_rmb": None, "public_daily_limit_rmb": None,
        "source_freshness": "页面抓取时间不等于账户状态或公告生效时间",
        "is_trade_instruction": False, "payment_rmb": 0.0,
    }
    reader = _TableReader()
    reader.feed(markup)
    if not any(re.search(r"[（(]" + code + r"[）)]", heading) for heading in reader.headings):
        result["error_kind"] = "fund_identity_unverified"
        return result
    state = _single_field(reader.rows, "申购状态")
    result["purchase_status"] = {
        "开放申购": "open", "限制大额申购": "limited", "暂停申购": "paused",
    }.get(state, "unknown")
    result["min_purchase_rmb"] = _money_text(_single_field(reader.rows, "申购起点"))
    result["public_daily_limit_rmb"] = _money_text(_single_field(reader.rows, "日累计申购限额"))
    rates = set()
    for section, cells in reader.rows:
        if section != "申购费率" or len(cells) < 2:
            continue
        tier = cells[0]
        small = re.fullmatch(r"小于([0-9.]+)(万)?元", tier)
        applies = tier in {"---", "--", "—"}
        if small:
            applies = decimal_value(small.group(1)) * (10000 if small.group(2) else 1) > 20
        # 部分页面把划线原价和优惠价放在同一格，划线移除后仍有分隔竖线。
        # 只允许两端分隔符，两个可见费率同时存在时继续返回未知。
        rate = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)%", cells[-1].strip("|"))
        if applies and rate and decimal_value(rate.group(1)) <= 100:
            rates.add(float(decimal_value(rate.group(1))))
    if len(rates) == 1:
        result["subscription_fee_rate_pct"] = rates.pop()
    if result["purchase_status"] == "unknown" or result["subscription_fee_rate_pct"] is None or result["min_purchase_rmb"] is None:
        result["error_kind"] = "public_fields_incomplete"
    return result


def _fetch_page(code):
    """固定HTTPS域名单次GET，无凭据、无重定向、无重试且限制响应大小。"""
    with httpx.Client(timeout=5.0, follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", PUBLIC_URL.format(code=code)) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError("公开页面超出大小上限")
            return bytes(body).decode(response.encoding or "utf-8", errors="strict")


def fetch_current_public_options(codes, *, fetch_page=None, now=None):
    """仅查询当前四只持仓代码，失败只返回未知，不调用模型或扩大基金范围。"""
    reader = fetch_page or _fetch_page
    results = []
    for code in sorted(set(codes) & SUPPORTED_CODES):
        try:
            results.append(parse_public_purchase_page(code, reader(code), now=now))
        except (httpx.HTTPError, ValueError, UnicodeError):
            # 不回显原始异常、代理地址、页面全文或任何请求头。
            results.append({
                "fund_code": code, "platform": "天天基金", "source": PUBLIC_URL.format(code=code),
                "evidence_scope": "public_only", "account_eligible": None,
                "daily_remaining_rmb": None, "purchase_status": "unknown",
                "subscription_fee_rate_pct": None, "min_purchase_rmb": None,
                "is_trade_instruction": False, "payment_rmb": 0.0,
                "error_kind": "public_source_unavailable",
            })
    return results
