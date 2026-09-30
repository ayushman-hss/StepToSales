"""A very small Telegram Bot API client.

Standard library only, so hosting needs no extra package. Long polling
(getUpdates) instead of a webhook: it works from a laptop with no public
address, and just as well once hosted.

The bot token is part of every request URL, so nothing here ever logs a URL.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

API = "https://api.telegram.org"


class TelegramError(Exception):
    """Telegram said no, or could not be reached."""


class TelegramConflict(TelegramError):
    """Another process is already reading this bot's messages (HTTP 409)."""


class TelegramClient:
    def __init__(self, token: str, api_url: str | None = None) -> None:
        self._base = f"{(api_url or API).rstrip('/')}/bot{token}"

    def _call(self, method: str, payload: dict | None = None, timeout: float = 15) -> Any:
        req = urllib.request.Request(
            f"{self._base}/{method}",
            data=json.dumps(payload or {}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                body = json.load(res)
        except urllib.error.HTTPError as e:
            try:
                body = json.load(e)
            except Exception:
                body = {"ok": False, "description": f"HTTP {e.code}"}
            if e.code == 409:
                raise TelegramConflict(body.get("description", "conflict")) from None
            if e.code == 401:
                raise TelegramError("The bot token was refused. Check TELEGRAM_BOT_TOKEN.") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise TelegramError(f"Could not reach Telegram ({reason})") from None
        if not body.get("ok"):
            raise TelegramError(body.get("description", "Telegram refused the request"))
        return body["result"]

    def get_me(self) -> dict:
        return self._call("getMe")

    def get_updates(self, offset: int, timeout: int = 20) -> list[dict]:
        return self._call(
            "getUpdates",
            {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]},
            timeout=timeout + 10,
        )

    def send_message(self, chat_id: int, text: str) -> dict:
        return self._call(
            "sendMessage",
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )
