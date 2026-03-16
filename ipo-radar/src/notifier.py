"""Notifier - Send alerts via Feishu (飞书) Webhook when actionable signals are detected.

Requires environment variable (set in .env):
    FEISHU_WEBHOOK_URL  - Custom bot Webhook URL from Feishu group settings

Usage::

    from src.notifier import FeishuNotifier
    notifier = FeishuNotifier()
    notifier.process_reports(reports)

Setup:
    飞书群 → 设置 → 群机器人 → 添加自定义机器人 → 复制 Webhook 地址
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import requests
from dotenv import load_dotenv

from src.scorer.signal_aggregator import AggregatedReport

load_dotenv()

logger = logging.getLogger(__name__)

_TIMEOUT = 15

# ---------------------------------------------------------------------------
# Card header color constants (Feishu interactive card)
# ---------------------------------------------------------------------------
_COLOR_RED = "red"        # Signal notifications (STRONG_OPPORTUNITY, breakout)
_COLOR_ORANGE = "orange"  # Lockup / risk warnings
_COLOR_BLUE = "blue"      # Daily summary / earnings


class FeishuNotifier:
    """Send Feishu (飞书) notifications for actionable IPO signals.

    Uses Feishu custom bot Webhook with interactive card messages.

    Triggers:
    - STRONG_OPPORTUNITY detected
    - Breakout signal confirmed
    - Lockup expiry within 3 days
    - First earnings report within 3 days
    """

    def __init__(self, webhook_url: str | None = None):
        self.webhook_url = webhook_url or os.getenv("FEISHU_WEBHOOK_URL", "")

    def is_configured(self) -> bool:
        """Check if Feishu Webhook URL is set."""
        return bool(self.webhook_url)

    def send_card(self, card: dict) -> bool:
        """Send an interactive card message via Feishu Webhook.

        Parameters
        ----------
        card : dict
            Feishu interactive card payload (the ``card`` field content).

        Returns True on success, False on failure.
        """
        if not self.is_configured():
            logger.warning("Feishu not configured (missing FEISHU_WEBHOOK_URL)")
            return False

        payload = {
            "msg_type": "interactive",
            "card": card,
        }

        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            result = resp.json()
            if result.get("code") == 0 or result.get("StatusCode") == 0:
                logger.info("Feishu message sent successfully")
                return True
            logger.warning("Feishu API returned error: %s", result)
            return False
        except Exception as exc:
            logger.warning("Feishu send failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Card builder helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_card(
        title: str,
        color: str,
        elements: list[dict],
    ) -> dict:
        """Build a Feishu interactive card structure.

        Parameters
        ----------
        title : str
            Card header title.
        color : str
            Header color template: 'red', 'orange', 'blue', etc.
        elements : list[dict]
            Card body elements (lark_md divs, hr, etc.).
        """
        return {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title,
                },
                "template": color,
            },
            "elements": elements,
        }

    @staticmethod
    def _md_element(content: str) -> dict:
        """Create a lark_md text element."""
        return {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": content,
            },
        }

    @staticmethod
    def _hr() -> dict:
        return {"tag": "hr"}

    @staticmethod
    def _note(text: str) -> dict:
        return {
            "tag": "note",
            "elements": [
                {"tag": "lark_md", "content": text},
            ],
        }

    # ------------------------------------------------------------------
    # Report processing
    # ------------------------------------------------------------------

    def process_reports(self, reports: list[AggregatedReport]) -> int:
        """Process scan reports and send notifications for actionable items.

        Returns the number of notifications sent.
        """
        if not self.is_configured():
            return 0

        sent = 0
        for report in reports:
            cards = self._build_cards(report)
            for card in cards:
                if self.send_card(card):
                    sent += 1

        return sent

    def _build_cards(self, report: AggregatedReport) -> list[dict]:
        """Build notification cards for a single report.

        Returns a list of card dicts (may be empty if no alert needed).
        """
        cards: list[dict] = []

        # 1. STRONG_OPPORTUNITY alert
        if report.overall_signal == "STRONG_OPPORTUNITY":
            cards.append(self._card_strong_opportunity(report))

        # 2. Breakout signal
        base = report.windows.get("ipo_base_breakout", {})
        if base.get("breakout_signal"):
            cards.append(self._card_breakout(report, base))

        # 3. Lockup expiry within 3 days
        lockup = report.windows.get("lockup_expiry", {})
        if lockup.get("status") == "imminent":
            cards.append(self._card_lockup_alert(report, lockup))

        # 4. First earnings within 3 days
        earnings = report.windows.get("first_earnings", {})
        days_until = earnings.get("days_until")
        if days_until is not None and 0 < days_until <= 3:
            cards.append(self._card_earnings_alert(report, earnings))

        return cards

    # ------------------------------------------------------------------
    # Card formatters
    # ------------------------------------------------------------------

    def _card_strong_opportunity(self, r: AggregatedReport) -> dict:
        price_str = f"${r.current_price:.2f}" if r.current_price else "N/A"
        vs_ipo_str = f"{(r.price_vs_ipo - 1) * 100:+.1f}%" if r.price_vs_ipo else "N/A"
        sentiment_score = r.sentiment.get("score", 0.0) if r.sentiment else 0.0

        reasons_md = "\n".join(
            f"• {reason}" for reason in r.signal_reasons
        ) if r.signal_reasons else "N/A"

        risks_md = "\n".join(
            f"• {risk}" for risk in r.risk_factors
        ) if r.risk_factors else "None"

        elements = [
            self._md_element(
                f"**🏢 公司:** {r.company or 'N/A'}\n"
                f"**💰 当前价:** {price_str} (vs 发行价 {vs_ipo_str})\n"
                f"**📈 基本面:** {r.fundamental_score}/100 | **情绪:** {sentiment_score:+.2f}"
            ),
            self._hr(),
            self._md_element(f"**📊 信号理由:**\n{reasons_md}"),
            self._hr(),
            self._md_element(f"**⚠️ 风险因素:**\n{risks_md}"),
            self._note(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
        ]

        return self._build_card(
            f"🚨 STRONG OPPORTUNITY: {r.ticker}",
            _COLOR_RED,
            elements,
        )

    def _card_breakout(self, r: AggregatedReport, base: dict) -> dict:
        price_str = f"${r.current_price:.2f}" if r.current_price else "N/A"
        strength = base.get("breakout_signal", "unknown")

        elements = [
            self._md_element(
                f"**🏢 公司:** {r.company or 'N/A'}\n"
                f"**💰 当前价:** {price_str}\n"
                f"**📊 信号强度:** {strength}"
            ),
            self._hr(),
            self._md_element("📉 IPO 底部形态确认 → **突破信号触发**"),
            self._note(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
        ]

        return self._build_card(
            f"💥 BREAKOUT: {r.ticker}",
            _COLOR_RED,
            elements,
        )

    def _card_lockup_alert(self, r: AggregatedReport, lockup: dict) -> dict:
        days = lockup.get("days_until", "?")
        supply = lockup.get("supply_impact_pct")
        supply_str = f"{supply:.0f}% of float" if supply else "未知"

        elements = [
            self._md_element(
                f"**🏢 公司:** {r.company or 'N/A'}\n"
                f"**⏰ 禁售期到期:** **{days} 天**后\n"
                f"**📉 潜在供给增加:** {supply_str}"
            ),
            self._hr(),
            self._md_element("⚠️ 预计将有较大抛压，请注意风险管理"),
            self._note(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
        ]

        return self._build_card(
            f"🔒 禁售期预警: {r.ticker}",
            _COLOR_ORANGE,
            elements,
        )

    def _card_earnings_alert(self, r: AggregatedReport, earnings: dict) -> dict:
        days = earnings.get("days_until", "?")

        elements = [
            self._md_element(
                f"**🏢 公司:** {r.company or 'N/A'}\n"
                f"**📊 首次财报发布:** **{days} 天**后\n"
                f"**💰 当前价:** ${r.current_price:.2f}\n"
                f"**📝 基本面评分:** {r.fundamental_score}/100"
            ),
            self._note(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
        ]

        return self._build_card(
            f"📅 财报预警: {r.ticker}",
            _COLOR_BLUE,
            elements,
        )
