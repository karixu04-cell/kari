"""Notifier - Send alerts via Telegram when actionable signals are detected.

Requires environment variables (set in .env):
    TELEGRAM_BOT_TOKEN  - Bot token from @BotFather
    TELEGRAM_CHAT_ID    - Target chat/channel ID

Usage::

    from src.notifier import TelegramNotifier
    notifier = TelegramNotifier()
    notifier.process_reports(reports)
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

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 15


class TelegramNotifier:
    """Send Telegram notifications for actionable IPO signals.

    Triggers:
    - STRONG_OPPORTUNITY detected
    - Breakout signal confirmed
    - Lockup expiry within 3 days
    - First earnings report within 3 days
    """

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

    def is_configured(self) -> bool:
        """Check if Telegram credentials are set."""
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str) -> bool:
        """Send a message via Telegram Bot API.

        Returns True on success, False on failure.
        """
        if not self.is_configured():
            logger.warning("Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
            return False

        url = _TELEGRAM_API.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            resp = requests.post(url, json=payload, timeout=_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()
            if result.get("ok"):
                logger.info("Telegram message sent successfully")
                return True
            logger.warning("Telegram API returned error: %s", result)
            return False
        except Exception as exc:
            logger.warning("Telegram send failed: %s", exc)
            return False

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
            messages = self._build_messages(report)
            for msg in messages:
                if self.send_message(msg):
                    sent += 1

        return sent

    def _build_messages(self, report: AggregatedReport) -> list[str]:
        """Build notification messages for a single report.

        Returns a list of messages (may be empty if no alert needed).
        """
        messages: list[str] = []

        # 1. STRONG_OPPORTUNITY alert
        if report.overall_signal == "STRONG_OPPORTUNITY":
            messages.append(self._format_strong_opportunity(report))

        # 2. Breakout signal
        base = report.windows.get("ipo_base_breakout", {})
        if base.get("breakout_signal"):
            messages.append(self._format_breakout(report, base))

        # 3. Lockup expiry within 3 days
        lockup = report.windows.get("lockup_expiry", {})
        if lockup.get("status") == "imminent":
            messages.append(self._format_lockup_alert(report, lockup))

        # 4. First earnings within 3 days
        earnings = report.windows.get("first_earnings", {})
        days_until = earnings.get("days_until")
        if days_until is not None and 0 < days_until <= 3:
            messages.append(self._format_earnings_alert(report, earnings))

        return messages

    # ------------------------------------------------------------------
    # Message formatters
    # ------------------------------------------------------------------

    def _format_strong_opportunity(self, r: AggregatedReport) -> str:
        price_str = f"${r.current_price:.2f}" if r.current_price else "N/A"
        vs_ipo_str = f"{(r.price_vs_ipo - 1) * 100:+.1f}%" if r.price_vs_ipo else "N/A"
        sentiment_score = r.sentiment.get("score", 0.0) if r.sentiment else 0.0

        reasons = "\n".join(f"  • {reason}" for reason in r.signal_reasons) if r.signal_reasons else "  N/A"
        risks = "\n".join(f"  • {risk}" for risk in r.risk_factors) if r.risk_factors else "  None"

        return (
            f"\U0001f6a8 <b>STRONG OPPORTUNITY: {r.ticker}</b>\n"
            f"\U0001f3e2 {r.company or 'N/A'}\n"
            f"\n"
            f"\U0001f4ca <b>Signal:</b>\n{reasons}\n"
            f"\n"
            f"\U0001f4b0 Price: {price_str} (vs IPO {vs_ipo_str})\n"
            f"\U0001f4c8 Fundamentals: {r.fundamental_score}/100 | Sentiment: {sentiment_score:+.2f}\n"
            f"\n"
            f"\u26a0\ufe0f <b>Risks:</b>\n{risks}\n"
            f"\n"
            f"\U0001f552 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )

    def _format_breakout(self, r: AggregatedReport, base: dict) -> str:
        price_str = f"${r.current_price:.2f}" if r.current_price else "N/A"
        strength = base.get("breakout_signal", "unknown")

        return (
            f"\U0001f4a5 <b>BREAKOUT: {r.ticker}</b>\n"
            f"\U0001f3e2 {r.company or 'N/A'}\n"
            f"\n"
            f"\U0001f4ca Signal strength: <b>{strength}</b>\n"
            f"\U0001f4b0 Price: {price_str}\n"
            f"\U0001f4c9 Base detected → Breakout confirmed\n"
            f"\n"
            f"\U0001f552 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )

    def _format_lockup_alert(self, r: AggregatedReport, lockup: dict) -> str:
        days = lockup.get("days_until", "?")
        supply = lockup.get("supply_impact_pct")
        supply_str = f"{supply:.0f}% of float" if supply else "unknown"

        return (
            f"\U0001f512 <b>LOCKUP ALERT: {r.ticker}</b>\n"
            f"\U0001f3e2 {r.company or 'N/A'}\n"
            f"\n"
            f"\u23f0 Lockup expires in <b>{days} days</b>\n"
            f"\U0001f4c9 Potential supply increase: {supply_str}\n"
            f"\u26a0\ufe0f Expect increased selling pressure\n"
            f"\n"
            f"\U0001f552 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )

    def _format_earnings_alert(self, r: AggregatedReport, earnings: dict) -> str:
        days = earnings.get("days_until", "?")

        return (
            f"\U0001f4c5 <b>EARNINGS ALERT: {r.ticker}</b>\n"
            f"\U0001f3e2 {r.company or 'N/A'}\n"
            f"\n"
            f"\U0001f4ca First earnings report in <b>{days} days</b>\n"
            f"\U0001f4b0 Current price: ${r.current_price:.2f}\n"
            f"\U0001f4dd Fundamental score: {r.fundamental_score}/100\n"
            f"\n"
            f"\U0001f552 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
