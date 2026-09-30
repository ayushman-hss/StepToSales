"""Watches every shop's day and tells its phone when something is off.

Two loops, one per API process (like the live simulator, run it once):

* the watcher, every few seconds: works out each shop's live view at its
  shop clock, raises any alerts that are due, records them (so each is raised
  once, ever) and sends them to the shop's linked Telegram chats;
* the bot, when TELEGRAM_BOT_TOKEN is set: reads messages sent to the bot --
  "/start <code>" links a chat to a shop, "/status" answers with today so
  far, "/stop" unlinks.

Alerts are recorded even with no bot configured, so the alerts page still
shows what would have been sent.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import threading
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ...models import AlertChat, AlertLinkCode, AlertSent, Store, utc_now
from ..live.clock import ist_now
from ..live.runner import CATCH_UP_AFTER
from ..live.today import today_view
from .rules import HOURLY, Alert, clock_hour, due_alerts, status_text
from .telegram import TelegramClient, TelegramConflict, TelegramError

log = logging.getLogger("steptosales.alerts")

WATCH_SECONDS = 4.0
POLL_TIMEOUT = 20
LINK_CODE_TTL = timedelta(minutes=15)

WHAT_YOU_GET = (
    "You'll get a message here when:\n"
    "\u2022 an hour is slow: fewer people came in, or fewer of them bought\n"
    "\u2022 an hour is busy: well above a usual one\n"
    "\u2022 the day is well behind, or well ahead of, a usual day\n"
    "\u2022 and a summary after closing."
)

COMMANDS_HELP = (
    "/status - how today is going right now\n"
    "/hourly - a short update after every hour (send again to turn off)\n"
    "/stop - stop sending alerts to this chat\n"
    "/help - this list"
)

HELP = (
    "This bot sends StepToSales alerts about your shop.\n"
    "To connect: open Phone alerts in StepToSales and tap Connect Telegram.\n\n"
    + COMMANDS_HELP
)

#: The menu Telegram shows when you type "/".
BOT_COMMANDS = [
    {"command": "status", "description": "How today is going right now"},
    {"command": "hourly", "description": "Turn hourly updates on or off"},
    {"command": "stop", "description": "Stop alerts to this chat"},
    {"command": "help", "description": "What this bot does"},
]


def _chat_title(chat: dict) -> str:
    if chat.get("title"):
        return chat["title"]
    name = " ".join(p for p in (chat.get("first_name"), chat.get("last_name")) if p)
    return name or (f"@{chat['username']}" if chat.get("username") else "Telegram chat")


def _heading(store: Store) -> str:
    return f"{store.code} · {store.name}" if store.name else store.code


class AlertService:
    def __init__(self, engine, runner, token: str | None = None,
                 client_factory: Callable[[str], TelegramClient] = TelegramClient) -> None:
        self.engine = engine
        self.runner = runner
        self.client = client_factory(token) if token else None
        self.bot_username: str | None = None
        #: Last problem talking to Telegram, shown on the alerts page.
        self.bot_error: str | None = None
        self._offset = 0
        self._task: asyncio.Task | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def configured(self) -> bool:
        return self.client is not None

    # ---- lifecycle ------------------------------------------------------

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._watch_loop())
        if self.client is not None and self._thread is None:
            # A plain daemon thread, not the event loop's executor: a long
            # poll must never hold up the API shutting down or reloading.
            self._stop.clear()
            self._thread = threading.Thread(target=self._bot_loop, name="telegram-bot",
                                            daemon=True)
            self._thread.start()

    async def stop(self) -> None:
        self._stop.set()
        self._thread = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _watch_loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.check_all)
            except Exception:  # an alert must never take the API down
                log.exception("alert check failed")
            await asyncio.sleep(WATCH_SECONDS)

    def _bot_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self.poll_once()
                backoff = 1.0
            except TelegramConflict:
                self.bot_error = (
                    "Another copy of StepToSales is reading this bot's messages. "
                    "Stop the other one, or give each copy its own bot."
                )
                self._stop.wait(10)
            except Exception as e:
                self.bot_error = str(e) if isinstance(e, TelegramError) else "Telegram bot error"
                if not isinstance(e, TelegramError):
                    log.exception("telegram bot loop failed")
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 60)

    # ---- the watcher ----------------------------------------------------

    def shop_clock(self, code: str) -> datetime | None:
        """The shop's clock, or None while it is still catching up on
        downtime -- alerts found in replayed hours would be old news."""
        now = ist_now()
        shop = self.runner.state(code) if self.runner is not None else None
        if shop is None:
            return now
        if shop.speed != 0 and shop.clock < now - CATCH_UP_AFTER:
            return None
        return shop.clock

    def check_all(self) -> int:
        """Raise whatever is due for every shop. Returns how many were raised."""
        raised = 0
        with Session(self.engine) as session:
            for store in session.exec(select(Store).order_by(Store.code)).all():
                clock = self.shop_clock(store.code)
                if clock is None:
                    continue
                view, totals = today_view(session, store, clock)
                if view is None or totals is None:
                    continue
                for alert in due_alerts(view, clock.date(), clock_hour(clock), totals):
                    if self.raise_alert(session, store, alert, clock):
                        raised += 1
        return raised

    def raise_alert(self, session: Session, store: Store, alert: Alert,
                    clock: datetime) -> AlertSent | None:
        """Record an alert and send it; None if it was already raised."""
        seen = session.exec(
            select(AlertSent.id)
            .where(AlertSent.store_id == store.id)
            .where(AlertSent.kind == alert.kind)
            .where(AlertSent.key == alert.key)
        ).first()
        if seen is not None:
            return None
        row = AlertSent(store_id=store.id, kind=alert.kind, key=alert.key,
                        text=alert.text, shop_time=clock.replace(microsecond=0))
        session.add(row)
        try:
            session.commit()
        except IntegrityError:        # raised by a parallel check a moment ago
            session.rollback()
            return None
        row.delivered = self.send_to_shop(
            session, store, f"{_heading(store)}\n{alert.text}",
            hourly_only=alert.kind == HOURLY,
        )
        session.add(row)
        session.commit()
        return row

    def send_to_shop(self, session: Session, store: Store, text: str,
                     hourly_only: bool = False) -> int:
        """Send to every chat linked to the shop (or only those that asked
        for hourly updates). Returns how many got it."""
        if self.client is None:
            return 0
        stmt = select(AlertChat).where(AlertChat.store_id == store.id)
        if hourly_only:
            stmt = stmt.where(AlertChat.hourly == True)  # noqa: E712 -- SQL, not Python
        chats = session.exec(stmt).all()
        delivered = 0
        for chat in chats:
            try:
                self.client.send_message(chat.chat_id, text)
                delivered += 1
            except TelegramError as e:
                # A chat that blocked the bot or was deleted: keep going.
                log.warning("could not send an alert to chat %s: %s", chat.id, e)
        return delivered

    # ---- linking --------------------------------------------------------

    def new_link_code(self, session: Session, store: Store) -> AlertLinkCode:
        session.execute(sa_delete(AlertLinkCode).where(AlertLinkCode.expires_at < utc_now()))
        code = AlertLinkCode(code=secrets.token_urlsafe(12), store_id=store.id,
                             expires_at=utc_now() + LINK_CODE_TTL)
        session.add(code)
        session.commit()
        session.refresh(code)
        return code

    def link_url(self, code: str) -> str | None:
        return f"https://t.me/{self.bot_username}?start={code}" if self.bot_username else None

    def link_chat(self, session: Session, code: str, chat: dict) -> Store | None:
        """Use a link code for this chat. None if the code is wrong or old."""
        row = session.get(AlertLinkCode, code)
        if row is None or row.expires_at < utc_now():
            return None
        store = session.get(Store, row.store_id)
        existing = session.exec(
            select(AlertChat)
            .where(AlertChat.store_id == row.store_id)
            .where(AlertChat.chat_id == int(chat["id"]))
        ).first()
        if existing is None:
            session.add(AlertChat(store_id=row.store_id, chat_id=int(chat["id"]),
                                  title=_chat_title(chat)))
        session.delete(row)          # one use only
        session.commit()
        return store

    # ---- the bot --------------------------------------------------------

    def poll_once(self) -> None:
        if self.client is None:
            return
        if self.bot_username is None:
            self.bot_username = self.client.get_me().get("username")
            try:
                self.client.set_commands(BOT_COMMANDS)
            except TelegramError as e:           # only the "/" menu is missing
                log.warning("could not set the bot's command menu: %s", e)
        updates = self.client.get_updates(self._offset, timeout=POLL_TIMEOUT)
        self.bot_error = None
        for update in updates:
            self._offset = max(self._offset, int(update["update_id"]) + 1)
            try:
                self.handle_update(update)
            except TelegramError as e:
                log.warning("could not answer a Telegram message: %s", e)

    def handle_update(self, update: dict) -> str | None:
        """Answer one message sent to the bot. Returns the reply, for tests."""
        message = update.get("message") or {}
        chat = message.get("chat")
        text = (message.get("text") or "").strip()
        if not chat or not text:
            return None
        command, _, arg = text.partition(" ")
        command = command.split("@", 1)[0].lower()

        with Session(self.engine) as session:
            if command == "/start" and arg.strip():
                store = self.link_chat(session, arg.strip(), chat)
                reply = (
                    f"Connected to {_heading(store)}.\n\n{WHAT_YOU_GET}\n\n{COMMANDS_HELP}"
                    if store else
                    "That link has expired or was already used. Open Phone alerts "
                    "in StepToSales and tap Connect Telegram again."
                )
            elif command == "/status":
                reply = self._status_reply(session, int(chat["id"]))
            elif command == "/hourly":
                reply = self._toggle_hourly(session, int(chat["id"]), arg.strip().lower())
            elif command == "/stop":
                rows = session.exec(
                    select(AlertChat).where(AlertChat.chat_id == int(chat["id"]))
                ).all()
                for row in rows:
                    session.delete(row)
                session.commit()
                reply = ("Done. This chat won't get alerts any more." if rows
                         else "This chat wasn't getting alerts.")
            else:
                reply = HELP

        if self.client is not None:
            self.client.send_message(int(chat["id"]), reply)
        return reply

    def _toggle_hourly(self, session: Session, chat_id: int, arg: str) -> str:
        rows = session.exec(select(AlertChat).where(AlertChat.chat_id == chat_id)).all()
        if not rows:
            return "This chat isn't connected to a shop yet.\n\n" + HELP
        on = {"on": True, "off": False}.get(arg, not all(r.hourly for r in rows))
        for row in rows:
            row.hourly = on
            session.add(row)
        session.commit()
        return (
            "Hourly updates on. After every hour the shop is open you'll get its "
            "takings against the usual, and the day so far. Send /hourly again to stop them."
            if on else
            "Hourly updates off. You'll still get alerts when something needs attention."
        )

    def _status_reply(self, session: Session, chat_id: int) -> str:
        stores = session.exec(
            select(Store)
            .join(AlertChat, AlertChat.store_id == Store.id)
            .where(AlertChat.chat_id == chat_id)
            .order_by(Store.code)
        ).all()
        if not stores:
            return "This chat isn't connected to a shop yet.\n\n" + HELP
        parts = []
        for store in stores:
            clock = self.shop_clock(store.code) or ist_now()
            view, totals = today_view(session, store, clock)
            parts.append(f"{_heading(store)}\n{status_text(view, totals, clock)}")
        return "\n\n".join(parts)

