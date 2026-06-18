"""Telegram receiver + sender, built on ``urllib`` (zero dependencies).

No LLM here. The **receiver** long-polls, enqueues each message onto the durable
queue, and acks "queued — working on it" (ali-fleet-recovery's daemon-bot: the
deterministic layer never blocks on the brain). Claude Code drains the queue and
replies with ``agent tg send <chat_id> "…"``.

Inherited: chat-id auto-capture into ``.env`` on first message, an allow-list, and
Markdown-with-plain-fallback sends.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from agent.config import Settings, get_settings, set_env_var
from agent.logging import get_logger

log = get_logger("channels.telegram")

API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4096


class TelegramClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def _call(self, method: str, params: dict | None = None, *, timeout: int = 35) -> dict:
        url = API.format(token=self.token, method=method)
        data = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"ok": False, "description": body}
            retry = (payload.get("parameters") or {}).get("retry_after")
            if retry:
                time.sleep(min(int(retry) + 1, 30))
            return payload
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "description": str(exc)}

    def send_message(
        self, text: str, chat_id: str | int, *, reply_to: int | None = None, markdown: bool = True
    ) -> dict:
        text = text if len(text) <= MAX_LEN else text[: MAX_LEN - 2] + "…"
        params: dict[str, Any] = {"chat_id": chat_id, "text": text or "…"}
        if markdown:
            params["parse_mode"] = "Markdown"
        if reply_to:
            params["reply_to_message_id"] = reply_to
        res = self._call("sendMessage", params)
        if not res.get("ok") and markdown:  # retry without markdown if parse failed
            params.pop("parse_mode", None)
            res = self._call("sendMessage", params)
        return res

    def get_updates(self, offset: int | None, *, timeout: int = 25) -> list[dict]:
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        res = self._call("getUpdates", params, timeout=timeout + 10)
        return res.get("result", []) if res.get("ok") else []

    def get_me(self) -> dict:
        return self._call("getMe")


def send(chat_id: str | int, text: str, settings: Settings | None = None) -> bool:
    """Send a message (chunked at 4096). Used by ``agent tg send``."""
    s = settings or get_settings()
    if not s.telegram_bot_token:
        return False
    client = TelegramClient(s.telegram_bot_token)
    text = text or "…"
    for i in range(0, len(text), MAX_LEN):
        res = client.send_message(text[i : i + MAX_LEN], chat_id)
        if not res.get("ok"):
            return False
    return True


def notify(text: str, settings: Settings | None = None) -> bool:
    """Proactively message the configured default chat."""
    s = settings or get_settings()
    if not s.telegram_chat_id:
        return False
    return send(s.telegram_chat_id, text, s)


class TelegramReceiver:
    """Long-poll, enqueue every message, ack. The deterministic, no-LLM layer."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()
        if not self.s.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
        self.client = TelegramClient(self.s.telegram_bot_token)

    def _authorized(self, user_id: int) -> bool:
        allow = self.s.telegram_allowed_user_ids
        return not allow or user_id in allow

    def run(self) -> None:
        me = self.client.get_me()
        if not me.get("ok"):
            raise RuntimeError(f"Telegram auth failed: {me.get('description')}")
        log.info("telegram receiver @%s online (enqueue mode)", me["result"].get("username"))
        offset: int | None = None
        while True:
            for upd in self.client.get_updates(offset):
                offset = upd["update_id"] + 1
                try:
                    self._handle(upd.get("message"))
                except Exception:
                    log.exception("error handling update")

    def _handle(self, msg: dict | None) -> None:
        if not msg or "text" not in msg:
            return
        chat_id = msg["chat"]["id"]
        user_id = (msg.get("from") or {}).get("id", 0)
        who = (msg.get("from") or {}).get("username") or (msg.get("from") or {}).get("first_name", "?")
        text = msg["text"].strip()
        mid = msg.get("message_id")

        if not self.s.telegram_chat_id:  # auto-capture the chat id once
            set_env_var("TELEGRAM_CHAT_ID", str(chat_id))
            self.s.telegram_chat_id = str(chat_id)

        if not self._authorized(user_id):
            self.client.send_message("Not authorized.", chat_id)
            return

        if text.startswith("/"):
            self._command(text, chat_id)
            return

        from agent.queue.task_queue import get_queue

        task_id, is_new = get_queue().add(
            text,
            kind="chat",
            source="telegram",
            external_id=f"{chat_id}:{mid}",
            origin={"channel": "telegram", "chat_id": chat_id, "msg_id": mid, "who": who},
        )
        who_acts = self.s.agent_name or "I'll"
        verb = "will work this" if self.s.agent_name else "work this"
        ack = (
            f"📥 Queued *#{task_id}* — {who_acts} {verb} and reply here."
            if is_new
            else f"already queued as #{task_id}"
        )
        self.client.send_message(ack, chat_id, reply_to=mid)

    def _command(self, text: str, chat_id: int) -> None:
        cmd = text.split()[0].lower().lstrip("/")
        if cmd in ("start", "help"):
            name = self.s.agent_name or "This agent"
            self.client.send_message(
                f"*{name}* is online. Send me anything — it goes on the work "
                "queue and I'll reply here. Commands: /status, /help",
                chat_id,
            )
        elif cmd == "status":
            from agent.queue.task_queue import get_queue

            self.client.send_message(f"queue: {get_queue().counts() or 'empty'}", chat_id, markdown=False)
        else:
            self.client.send_message("Unknown command. Try /help.", chat_id)
