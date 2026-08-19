"""Mail service - send formatted portfolio analysis reports via SMTP."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional

from backend.config import get_settings

logger = logging.getLogger(__name__)


class MailService:
    """Send portfolio analysis reports and notifications via email."""

    def __init__(self):
        self.settings = get_settings()
        self._configured = bool(
            self.settings.SMTP_HOST
            and self.settings.SMTP_PORT
            and self.settings.SMTP_USER
            and self.settings.SMTP_PASSWORD
            and self.settings.SMTP_TO
        )
        self._app_name = "FundAdvisor"

    @property
    def configured(self) -> bool:
        return self._configured

    def send_analysis_report(self, analysis_result: dict) -> bool:
        """Send a formatted analysis report email."""
        if not self._configured:
            logger.warning("SMTP not configured, skipping email")
            return False

        subject = self._build_subject()
        html = self._build_html_report(analysis_result)
        return self._send(subject, html)

    def send_simple_notification(self, title: str, body: str) -> bool:
        """Send a simple text notification."""
        if not self._configured:
            return False
        html = "<p>{}</p>".format(body)
        return self._send("[FundAdvisor] " + title, html)

    def _build_subject(self) -> str:
        date_str = datetime.now().strftime("%Y-%m-%d")
        return "[FundAdvisor] 持仓分析报告 - " + date_str

    def _send(self, subject: str, html: str) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.settings.SMTP_USER
            msg["To"] = self.settings.SMTP_TO
            msg["Subject"] = subject
            msg.attach(MIMEText(html, "html", "utf-8"))

            logger.info("Sending email to {to} via {host}:{port}".format(
                to=self.settings.SMTP_TO,
                host=self.settings.SMTP_HOST,
                port=self.settings.SMTP_PORT,
            ))

            with smtplib.SMTP_SSL(
                self.settings.SMTP_HOST, self.settings.SMTP_PORT, timeout=30
            ) as server:
                server.login(self.settings.SMTP_USER, self.settings.SMTP_PASSWORD)
                server.send_message(msg)

            logger.info("Email sent successfully")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP authentication failed")
        except smtplib.SMTPRecipientsRefused:
            logger.error("SMTP recipient refused: " + str(self.settings.SMTP_TO))
        except smtplib.SMTPServerDisconnected:
            logger.error("SMTP server disconnected")
        except TimeoutError:
            logger.error("SMTP connection timeout")
        except Exception as e:
            logger.error("Failed to send email: {err}".format(err=e))

        return False

    def _build_html_report(self, analysis: dict) -> str:
        # RFC-021: 金额基准优先取报告自带的 incremental_allocation(含可用增量资金/目标盘子)
        # 回退: 从 config_service 读 available_capital
        alloc_meta = analysis.get("incremental_allocation") if isinstance(analysis.get("incremental_allocation"), dict) else None
        base_amt = None
        base_notes = []
        if alloc_meta:
            base_amt = alloc_meta.get("available_capital")
            base_notes = alloc_meta.get("notes", [])
        else:
            base_amt = None
            try:
                from backend.services.config_service import get_available_capital
                from backend.database import SessionLocal
                _db = SessionLocal()
                try:
                    base_amt = get_available_capital(_db)
                finally:
                    _db.close()
            except Exception:  # noqa: BLE001
                base_amt = None

        # 构建 基金代码→名称 映射(供盘中速览显示友好名称)
        code_names = {}
        for h in analysis.get("holdings_health", []) or []:
            c = h.get("fund_code") or h.get("code")
            if c:
                code_names[c] = h.get("fund_name") or h.get("name") or c
        for a in analysis.get("actions", []) or []:
            c = a.get("fund_code")
            if c and c not in code_names:
                code_names[c] = a.get("fund_name") or c

        parts = []
        parts.append(self._html_head(analysis))
        parts.append(self._html_market_analysis(analysis.get("market_analysis", {})))
        parts.append(self._html_intraday_view(analysis.get("intraday_view", {}), code_names))
        health_rows = self._html_health_rows(analysis.get("holdings_health", []))
        if health_rows:
            parts.append(self._html_section_title("持仓健康度"))
            parts.append(health_rows)
        action_rows = self._html_action_rows(analysis.get("actions", []), base_amt, alloc_meta=alloc_meta)
        if action_rows:
            parts.append(self._html_section_title("操作建议"))
            parts.append(action_rows)
        parts.append(self._html_diagnosis(analysis.get("portfolio_diagnosis", {})))
        parts.append(self._html_footer(analysis))
        return "\n".join(parts)

    def _html_head(self, analysis: dict) -> str:
        return """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, sans-serif; max-width: 680px; margin: 0 auto; padding: 20px; color: #333;">
    <div style="text-align: center; margin-bottom: 24px;">
        <h1 style="font-size: 22px; margin: 0; color: #409eff;">持仓分析报告</h1>
        <p style="color: #999; font-size: 13px;">{dt} | 模型: {model}</p>
    </div>""".format(
            dt=analysis.get("generated_at", ""),
            model=analysis.get("model", ""),
        )

    def _html_market_analysis(self, ma: dict) -> str:
        return """    <div style="background: #f0f9ff; border-left: 4px solid #409eff; padding: 16px; margin-bottom: 20px; border-radius: 4px;">
        <h2 style="margin: 0 0 8px 0; font-size: 16px;">市场环境</h2>
        <p style="margin: 4px 0; color: #606266;"><strong>趋势：</strong>{trend}</p>
        <p style="margin: 4px 0; color: #606266;">{overall}</p>
    </div>""".format(
            trend=ma.get("trend", "N/A"),
            overall=ma.get("overall", ""),
        )

    def _html_section_title(self, title: str) -> str:
        return '    <h2 style="font-size: 16px; margin-top: 20px;">{t}</h2>'.format(t=title)

    def _html_intraday_view(self, intraday: dict, code_names: dict = None) -> str:
        if not intraday or not isinstance(intraday, dict):
            return ""
        code_names = code_names or {}
        rows = []
        rows.append('<div style="background:#f0f9ff;border-left:4px solid #409eff;padding:12px 16px;margin-bottom:20px;border-radius:4px;">')
        rows.append('<h2 style="margin:0 0 6px 0;font-size:16px;">今日盘中涨跌速览</h2>')
        rows.append('<p style="margin:0 0 8px 0;color:#909399;font-size:12px;">实时指数快照 · 13:30未收盘,但方向感已足够参考 · 非精确基金净值</p>')
        rows.append('<table style="width:100%;border-collapse:collapse;">')
        rows.append('<thead><tr style="background:#f5f7fa">'
                    '<th style="padding:6px;text-align:left">基金</th>'
                    '<th style="padding:6px;text-align:left">跟踪指数</th>'
                    '<th style="padding:6px;text-align:left">今日涨跌</th>'
                    '<th style="padding:6px;text-align:left">vs5日线</th>'
                    '<th style="padding:6px;text-align:left">择时意见</th></tr></thead><tbody>')
        for code, iv in intraday.items():
            if not isinstance(iv, dict):
                continue
            fund = iv.get("fund_name") or code_names.get(code) or code
            idx = iv.get("index", "-")
            pct = iv.get("pct_today")
            ma = iv.get("vs_ma5")
            adv = iv.get("execution_advice", "观望")
            if pct is not None:
                pct_s = ("+" if pct > 0 else "") + "{:.2f}%".format(pct)
                pct_color = "#f56c6c" if pct > 0 else ("#67c23a" if pct < 0 else "#606266")
            else:
                pct_s, pct_color = "—", "#909399"
            ma_s = "—"
            if ma is not None:
                ma_s = ("+" if ma > 0 else "") + "{:.2f}%".format(ma)
            rows.append("""<tr>
                <td style="padding:6px">{fund}</td>
                <td style="padding:6px;color:#909399">{idx}</td>
                <td style="padding:6px;color:{pct_color};font-weight:600">{pct_s}</td>
                <td style="padding:6px;color:#909399">{ma_s}</td>
                <td style="padding:6px">{adv}</td>
            </tr>""".format(
                fund=fund, idx=idx, pct_s=pct_s, pct_color=pct_color, ma_s=ma_s, adv=adv
            ))
        rows.append("</tbody></table>")
        rows.append("</div>")
        return "\n".join(rows)

    def _html_health_rows(self, items: list) -> str:
        if not items:
            return ""
        rows = []
        rows.append('<table style="width:100%;border-collapse:collapse;margin-bottom:20px">')
        rows.append('<thead><tr style="background:#f5f7fa">'
                    '<th style="padding:8px;text-align:left">代码</th>'
                    '<th style="padding:8px;text-align:left">名称</th>'
                    '<th style="padding:8px;text-align:left">健康分</th>'
                    '<th style="padding:8px;text-align:left">风险</th>'
                    '<th style="padding:8px;text-align:left">建议</th></tr></thead><tbody>')
        for h in items:
            score = h.get("health_score", 0)
            color = "#67c23a" if score >= 70 else "#e6a23c" if score >= 40 else "#f56c6c"
            rows.append("""<tr>
                <td style="padding:8px">{code}</td>
                <td style="padding:8px">{name}</td>
                <td style="padding:8px;color:{color};font-weight:600">{score}</td>
                <td style="padding:8px">{concern}</td>
                <td style="padding:8px">{sug}</td>
            </tr>""".format(
                code=h.get("fund_code", ""),
                name=h.get("fund_name", ""),
                color=color,
                score=score,
                concern=h.get("concerns", ""),
                sug=h.get("suggestion", ""),
            ))
        rows.append("</tbody></table>")
        return "\n".join(rows)

    def _html_action_rows(self, items: list, available_capital: Optional[float] = None,
                          alloc_meta: Optional[dict] = None) -> str:
        if not items:
            return ""
        # RFC-021: 金额基准说明 — 目标盘子 = 现有持仓 + 可用增量资金
        alloc_notes = (alloc_meta or {}).get("notes") or []
        has_amounts = any(
            (a.get("current_amount") is not None or a.get("target_amount") is not None)
            for a in items
        )
        if alloc_notes:
            base_note = ('<p style="margin:4px 0 10px 0;color:#606266;font-size:13px;'
                         'background:#f5f7fa;padding:8px 12px;border-radius:4px;">'
                         + "；".join(alloc_notes)
                         + '</p>')
        elif available_capital is not None:
            try:
                ac = float(available_capital)
                base_note = ('<p style="margin:4px 0 10px 0;color:#606266;font-size:13px;'
                             'background:#f5f7fa;padding:8px 12px;border-radius:4px;">'
                             '可用增量资金 <strong>{amt}</strong> 元，加仓金额在现有持仓市值基础上按目标仓位分配。'
                             '</p>').format(amt=self._fmt_amt(ac))
            except (TypeError, ValueError):
                base_note = ""
        else:
            base_note = ('<p style="margin:4px 0 10px 0;color:#606266;font-size:13px;'
                         'background:#f5f7fa;padding:8px 12px;border-radius:4px;">'
                         '未设置可用增量资金，金额按当前持仓市值口径估算。</p>')
        action_labels = {
            "add": "加仓",
            "buy": "买入",
            "increase": "加仓",
            "reduce": "减仓",
            "sell": "卖出",
            "hold": "持有",
            "watch": "关注",
        }
        # 金额列是否展开为“现持→目标”
        show_amount_transition = has_amounts
        rows = []
        rows.append('<table style="width:100%;border-collapse:collapse;margin-bottom:20px">')
        if show_amount_transition:
            rows.append('<thead><tr style="background:#f5f7fa">'
                        '<th style="padding:8px;text-align:left">代码</th>'
                        '<th style="padding:8px;text-align:left">名称</th>'
                        '<th style="padding:8px;text-align:left">操作</th>'
                        '<th style="padding:8px;text-align:left">现持</th>'
                        '<th style="padding:8px;text-align:left">目标</th>'
                        '<th style="padding:8px;text-align:left">操作金额(元)</th>'
                        '<th style="padding:8px;text-align:left">理由</th></tr></thead><tbody>')
        else:
            rows.append('<thead><tr style="background:#f5f7fa">'
                        '<th style="padding:8px;text-align:left">代码</th>'
                        '<th style="padding:8px;text-align:left">名称</th>'
                        '<th style="padding:8px;text-align:left">操作</th>'
                        '<th style="padding:8px;text-align:left">金额(元)</th>'
                        '<th style="padding:8px;text-align:left">理由</th></tr></thead><tbody>')
        for a in items:
            label = action_labels.get(a.get("action", ""), a.get("action", ""))
            priority = a.get("priority", "")
            reason = a.get("reason", "")
            amount = a.get("action_amount")
            if amount is None:
                amount_str = a.get("action_amount_str", "--")
            else:
                amount = float(amount)
                if amount > 0:
                    amount_str = "+{:.2f}".format(amount)
                elif amount < 0:
                    amount_str = "-{:.2f}".format(abs(amount))
                else:
                    amount_str = "0.00"
            amount_color = "#389e0d" if a.get("action") in ("buy", "add", "increase") else ("#d4380d" if a.get("action") in ("reduce", "sell") else "#606266")
            if priority == "high":
                reason += " [高优]"
            cur = a.get("current_amount")
            tgt = a.get("target_amount")
            cur_str = self._fmt_amt(cur) if cur is not None else "--"
            tgt_str = self._fmt_amt(tgt) if tgt is not None else "--"
            if show_amount_transition:
                rows.append("""<tr>
                    <td style="padding:8px">{code}</td>
                    <td style="padding:8px">{name}</td>
                    <td style="padding:8px">{label}</td>
                    <td style="padding:8px">{cur}</td>
                    <td style="padding:8px">{tgt}</td>
                    <td style="padding:8px;color:{amount_color};font-weight:600">{amount_str}</td>
                    <td style="padding:8px">{reason}</td>
                </tr>""".format(
                    code=a.get("fund_code", ""),
                    name=a.get("fund_name", ""),
                    label=label,
                    cur=cur_str,
                    tgt=tgt_str,
                    amount_str=amount_str,
                    amount_color=amount_color,
                    reason=reason,
                ))
            else:
                rows.append("""<tr>
                    <td style="padding:8px">{code}</td>
                    <td style="padding:8px">{name}</td>
                    <td style="padding:8px">{label}</td>
                    <td style="padding:8px;color:{amount_color};font-weight:600">{amount_str}</td>
                    <td style="padding:8px">{reason}</td>
                </tr>""".format(
                    code=a.get("fund_code", ""),
                    name=a.get("fund_name", ""),
                    label=label,
                    amount_str=amount_str,
                    amount_color=amount_color,
                    reason=reason,
                ))
        rows.append("</tbody></table>")
        return base_note + "\n" + "\n".join(rows)

    @staticmethod
    def _fmt_amt(v: float) -> str:
        """格式化金额(保留两位)."""
        return "{:.2f}".format(v)


    def _html_diagnosis(self, d: dict) -> str:
        return """    <div style="background: #fefce8; border: 1px solid #fde68a; padding: 16px; border-radius: 4px; margin-bottom: 20px;">
        <h2 style="margin: 0 0 8px 0; font-size: 16px;">组合诊断</h2>
        <p style="margin: 4px 0; color: #606266;"><strong>集中度风险：</strong>{risk}</p>
        <p style="margin: 4px 0; color: #606266;"><strong>调仓建议：</strong>{rebalance}</p>
        <p style="margin: 4px 0; color: #606266;"><strong>整体评价：</strong>{assessment}</p>
    </div>""".format(
            risk=d.get("concentration_risk", ""),
            rebalance=d.get("rebalance_suggestion", ""),
            assessment=d.get("overall_assessment", ""),
        )

    def _html_footer(self, analysis: dict) -> str:
        return """    <div style="text-align:center;color:#999;font-size:12px;border-top:1px solid #eee;padding-top:12px;margin-top:20px;">
        <p style="margin:0">本报告由 FundAdvisor AI 自动生成，仅供参考，不构成投资建议。</p>
        <p style="margin:4px 0 0 0">模型: {model}</p>
    </div>
</body>
</html>""".format(
            model=analysis.get("model", ""),
        )
