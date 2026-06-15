"""Telegram client + bot, built on ``urllib`` (zero dependencies).

Inherited wholesale in spirit from ali-fleet-recovery's ``telegram.py`` +
``sentinel-bot.py``: long-poll loop, ``chat_id`` auto-capture into ``.env`` on
first message, an allow-list, and Markdown-with-plain-fallback sends. Replies
stream into a single message with a throttled edit (the n3d1117 pattern) so you
watch the agent think without tripping Telegram's flood limits.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from scion.config import Settings, get_settings, set_env_var
from scion.logging import get_logger

log = get_logger("channels.telegram")

API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4096


class TelegramClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def _call(self, method: str, params: dict | None = None, *, timeout: int = 35) -> dict:
        url = API.format(token=self.token, method=method)
        data = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"ok": False, "description": body}
            # honor flood-control backoff
            retry = (payload.get("parameters") or {}).get("retry_after")
            if retry:
                time.sleep(min(int(retry) + 1, 30))
            return payload
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "description": str(exc)}

    # ---- sends ------------------------------------------------------------ #
    def send_message(
        self,
        text: str,
        chat_id: str | int,
        *,
        reply_to: int | None = None,
        buttons: list[list[dict]] | None = None,
        silent: bool = False,
        markdown: bool = True,
    ) -> dict:
        text = text if len(text) <= MAX_LEN else text[: MAX_LEN - 2] + "…"
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text or "…",
            "disable_notification": silent,
        }
        if markdown:
            params["parse_mode"] = "Markdown"
        if reply_to:
            params["reply_to_message_id"] = reply_to
        if buttons:
            params["reply_markup"] = json.dumps({"inline_keyboard": buttons})
        res = self._call("sendMessage", params)
        if not res.get("ok") and markdown:  # markdown parse failed -> retry plain
            params.pop("parse_mode", None)
            res = self._call("sendMessage", params)
        return res

    def edit_message_text(
        self, text: str, chat_id: str | int, message_id: int, *, markdown: bool = False
    ) -> dict:
        text = text if len(text) <= MAX_LEN else text[: MAX_LEN - 2] + "…"
        params: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text or "…"}
        if markdown:
            params["parse_mode"] = "Markdown"
        return self._call("editMessageText", params)

    def answer_callback(self, callback_query_id: str, text: str = "") -> dict:
        return self._call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})

    def get_updates(self, offset: int | None, *, timeout: int = 25) -> list[dict]:
        params = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        res = self._call("getUpdates", params, timeout=timeout + 10)
        return res.get("result", []) if res.get("ok") else []

    def get_me(self) -> dict:
        return self._call("getMe")


class StreamEditor:
    """Stream a reply into one message, editing it with a char/time throttle."""

    def __init__(self, client: TelegramClient, chat_id: str | int, message_id: int) -> None:
        self.client = client
        self.chat_id = chat_id
        self.message_id = message_id
        self.buffer = ""
        self._last_len = 0
        self._last_at = 0.0

    def feed(self, delta: str) -> None:
        self.buffer += delta
        now = time.time()
        if len(self.buffer) - self._last_len >= 80 and (now - self._last_at) >= 1.2:
            self._flush_partial()

    def _flush_partial(self) -> None:
        text = (self.buffer[:MAX_LEN] + " …") if len(self.buffer) > MAX_LEN else self.buffer
        if text.strip():
            self.client.edit_message_text(text, self.chat_id, self.message_id)
            self._last_len = len(self.buffer)
            self._last_at = time.time()

    def finalize(self, text: str | None = None) -> None:
        final = (text if text is not None else self.buffer).strip() or "(no reply)"
        if len(final) <= MAX_LEN:
            self.client.edit_message_text(final, self.chat_id, self.message_id)
            return
        # too long: first chunk edits, the rest are new messages
        self.client.edit_message_text(final[:MAX_LEN], self.chat_id, self.message_id)
        for i in range(MAX_LEN, len(final), MAX_LEN):
            self.client.send_message(final[i : i + MAX_LEN], self.chat_id, markdown=False)


class TelegramChannel:
    """Channel adapter for a single chat. Confirmation is disabled by default
    (re-entrant inline approval is a documented extension point); high-risk tools
    therefore require ``SCION_REQUIRE_CONFIRMATION=0`` to run over Telegram."""

    can_confirm = False

    def __init__(self, client: TelegramClient, chat_id: str | int) -> None:
        self.client = client
        self.chat_id = chat_id

    def send(self, text: str) -> None:
        for i in range(0, max(len(text), 1), MAX_LEN):
            self.client.send_message(text[i : i + MAX_LEN] or "…", self.chat_id)

    def confirm(self, prompt: str) -> bool:  # pragma: no cover - intentionally inert
        self.send("⚠️ " + prompt + "\n(confirmation over Telegram is disabled; not running.)")
        return False


# --------------------------------------------------------------------------- #
# the bot
# --------------------------------------------------------------------------- #
class TelegramBot:
    def __init__(self, settings: Settings | None = None, agent_loop=None) -> None:
        self.s = settings or get_settings()
        if not self.s.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
        self.client = TelegramClient(self.s.telegram_bot_token)
        self._loop = agent_loop  # lazily built to avoid importing the world early
        self._sessions: dict[int, str] = {}

    def _agent(self):
        if self._loop is None:
            from scion.agent.loop import AgentLoop

            self._loop = AgentLoop(self.s)
        return self._loop

    # ---- run -------------------------------------------------------------- #
    def run(self) -> None:
        me = self.client.get_me()
        if not me.get("ok"):
            raise RuntimeError(f"Telegram auth failed: {me.get('description')}")
        log.info("telegram bot @%s online", me["result"].get("username"))
        offset: int | None = None
        while True:
            for upd in self.client.get_updates(offset):
                offset = upd["update_id"] + 1
                try:
                    self._dispatch(upd)
                except Exception:
                    log.exception("error handling update")

    def _dispatch(self, upd: dict) -> None:
        msg = upd.get("message")
        if not msg or "text" not in msg:
            return
        self._handle_message(msg)

    def _authorized(self, user_id: int) -> bool:
        allow = self.s.telegram_allowed_user_ids
        return not allow or user_id in allow

    def _handle_message(self, msg: dict) -> None:
        chat_id = msg["chat"]["id"]
        user_id = (msg.get("from") or {}).get("id", 0)
        text = msg["text"].strip()

        # auto-capture the chat id once (ali-fleet-recovery trick)
        if not self.s.telegram_chat_id:
            set_env_var("TELEGRAM_CHAT_ID", str(chat_id))
            self.s.telegram_chat_id = str(chat_id)

        if not self._authorized(user_id):
            self.client.send_message("Not authorized.", chat_id)
            return

        if text.startswith("/"):
            self._handle_command(text, chat_id)
            return

        self._run_agent(text, chat_id, msg.get("message_id"))

    def _handle_command(self, text: str, chat_id: int) -> None:
        cmd = text.split()[0].lower().lstrip("/")
        if cmd in ("start", "help"):
            self.client.send_message(
                f"*{self.s.agent_name}* online. Send me anything and I'll work it.\n\n"
                "Commands: /status, /reset, /help",
                chat_id,
            )
        elif cmd == "status":
            from scion.queue.task_queue import get_queue

            counts = get_queue().counts()
            tools = len(self._agent().registry)
            self.client.send_message(
                f"tools: {tools}\nqueue: {counts or 'empty'}", chat_id, markdown=False
            )
        elif cmd == "reset":
            self._sessions.pop(chat_id, None)
            self.client.send_message("Fresh session started.", chat_id)
        else:
            self.client.send_message("Unknown command. Try /help.", chat_id)

    def _run_agent(self, text: str, chat_id: int, reply_to: int | None) -> None:
        from scion.agent.session import Session

        placeholder = self.client.send_message("…", chat_id, reply_to=reply_to)
        message_id = (placeholder.get("result") or {}).get("message_id")
        editor = StreamEditor(self.client, chat_id, message_id) if message_id else None

        sid = self._sessions.get(chat_id)
        session = (Session.load(sid) if sid else None) or Session.new("tg")
        self._sessions[chat_id] = session.id
        channel = TelegramChannel(self.client, chat_id)

        try:
            final = self._agent().run(
                text,
                session=session,
                channel=channel,
                on_text=(editor.feed if editor else None),
            )
        except Exception as exc:
            final = f"⚠️ error: {exc}"
        if editor:
            editor.finalize(final)
        elif message_id is None:
            self.client.send_message(final or "(no reply)", chat_id)


def notify(text: str, settings: Settings | None = None) -> bool:
    """Proactively push a message to the configured default chat."""
    s = settings or get_settings()
    if not (s.telegram_bot_token and s.telegram_chat_id):
        return False
    res = TelegramClient(s.telegram_bot_token).send_message(text, s.telegram_chat_id)
    return bool(res.get("ok"))
