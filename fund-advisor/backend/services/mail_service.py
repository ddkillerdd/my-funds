"""Mail service - send formatted portfolio analysis reports via SMTP."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

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
        parts = []
        parts.append(self._html_head(analysis))
        parts.append(self._html_market_analysis(analysis.get("market_analysis", {})))
        health_rows = self._html_health_rows(analysis.get("holdings_health", []))
        if health_rows:
            parts.append(self._html_section_title("持仓健康度"))
            parts.append(health_rows)
        action_rows = self._html_action_rows(analysis.get("actions", []))
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

    def _html_action_rows(self, items: list) -> str:
        if not items:
            return ""
        action_labels = {
            "add": "加仓",
            "reduce": "减仓",
            "hold": "持有",
            "watch": "关注",
        }
        rows = []
        rows.append('<table style="width:100%;border-collapse:collapse;margin-bottom:20px">')
        rows.append('<thead><tr style="background:#f5f7fa">'
                    '<th style="padding:8px;text-align:left">代码</th>'
                    '<th style="padding:8px;text-align:left">名称</th>'
                    '<th style="padding:8px;text-align:left">操作</th>'
                    '<th style="padding:8px;text-align:left">理由</th></tr></thead><tbody>')
        for a in items:
            label = action_labels.get(a.get("action", ""), a.get("action", ""))
            priority = a.get("priority", "")
            reason = a.get("reason", "")
            if priority == "high":
                reason += " [高优]"
            rows.append("""<tr>
                <td style="padding:8px">{code}</td>
                <td style="padding:8px">{name}</td>
                <td style="padding:8px">{label}</td>
                <td style="padding:8px">{reason}</td>
            </tr>""".format(
                code=a.get("fund_code", ""),
                name=a.get("fund_name", ""),
                label=label,
                reason=reason,
            ))
        rows.append("</tbody></table>")
        return "\n".join(rows)

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
