# Telegram 🤖

Telegram is scion's front door — but **there is no LLM in this path.** A
deterministic **receiver** long-polls Telegram, drops every incoming message onto
the durable queue, and immediately acks *"queued — working on it."* The **brain**
(your Claude Code session, looping over `scion autopilot`) drains that queue later
and replies with `scion tg send <chat_id> "…"`. The receiver never calls the
model, so it never blocks on it and nothing is lost if the brain is busy or down.

Everything here lives in [`scion/channels/telegram.py`](../scion/channels/telegram.py)
(built on `urllib`, zero extra dependencies). Run `scion doctor` at any point — its
**channels** section reports whether the token is set and what `chat_id` it will use.

---

## 1. Create a bot and set the token

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, pick a name and a `@username`, and copy the **HTTP API token**
   it gives you (looks like `123456789:AAE…`).
3. Paste it into `.env`:

   ```bash
   TELEGRAM_BOT_TOKEN=123456789:AAE...your-token...
   ```

That's the **only** value you must set by hand. There is **no API key anywhere** —
scion has none; the brain is your Claude Code subscription, not a hosted model.
On startup the receiver calls Telegram's `getMe`; if the token is bad it fails
loudly with `Telegram auth failed`.

---

## 2. chat-id auto-capture (you don't set it by hand)

Leave `TELEGRAM_CHAT_ID` **blank**. The **first message the bot receives** triggers
auto-capture: the receiver reads the incoming `chat.id` and writes it back into
`.env` for you, so the next run already knows where "home" is.

The write-back is `set_env_var` in [`scion/config.py`](../scion/config.py) — it
create-or-updates the `TELEGRAM_CHAT_ID=` line in `.env` *and* the live environment
in one shot. After your first "hi" you'll see the line populated:

```bash
TELEGRAM_CHAT_ID=987654321
```

This captured chat is the **default chat** for proactive pushes (see §7). To move
"home" to a different chat or group, clear the line and message the bot again.

---

## 3. The allow-list (set this before you expose the bot)

`TELEGRAM_ALLOWED_USER_IDS` is a **comma-separated list of numeric Telegram user
IDs** allowed to command the agent:

```bash
TELEGRAM_ALLOWED_USER_IDS=987654321,123123123
```

- **Empty (default) = anyone** in chats the bot is in may drive it. Fine for a
  private bot only you can reach; **strongly** lock it down for anything else.
- Set it, and any other sender just gets a flat `Not authorized.` reply.
- The check is **per user** (`message.from.id`), so it filters individuals even in
  a shared group. Separators may be commas or semicolons; non-numeric junk is
  ignored (`_list_int` in `config.py`).

This is your **main gate** — there's no secret in the request path, so the
allow-list is what keeps strangers from queueing work.

**Finding your user id:** message [@userinfobot](https://t.me/userinfobot) (or
@RawDataBot) — it replies with your numeric `Id`. Put that number in the list.

---

## 4. The two halves: how a message flows end to end

scion splits Telegram into a deterministic half and a thinking half. They meet only
at the durable queue.

```
  you ──▶ Telegram ──▶ RECEIVER  (scion tg receive  /  scion sentinel)
                          │  enqueue onto the durable queue (SQLite)
                          │  ack:  "📥 Queued *#7* — Scion will work this and reply here."
                          ▼
                     durable queue  ── nothing is lost; the receiver is done here
                          │
                          ▼
   BRAIN  (a Claude Code session on  /loop scion autopilot)
      scion autopilot              → claims task #7, prints its chat_id + text
      …does the work with native tools + the scion CLI…
      scion tg send <chat_id> "…"  ──▶ Telegram ──▶ you
      scion task done 7 --result "…"
```

**(a) The receiver** (`scion tg receive`, or the Telegram half of `scion sentinel`)
long-polls, and for every authorized non-command message it calls
`get_queue().add(text, kind="chat", source="telegram", …)` — recording the
`chat_id` and message id in the task's `origin` — then replies in-thread with
`📥 Queued *#N* — Scion will work this and reply here.` (a repeat of an already-queued
message just gets `already queued as #N`). **That's all it does. It never calls the
model.**

**(b) The brain** picks the task up on its next cycle. `scion autopilot` claims the
oldest task and prints it, and for a Telegram-origin task it prints the exact reply
line to use:

```
  reply:  scion tg send 987654321 "<your reply>"
  close:  scion task done 7 --result "<one-line summary>"
```

The brain does the work, sends its answer back to that `chat_id`, and closes the
task. The `chat_id` always comes from autopilot's printed task — you never guess it.

---

## 5. Running it

```bash
scion sentinel        # receiver + cron together, restart-on-crash (the daemon)
scion tg receive      # just the receiver, in the foreground
```

`scion sentinel` runs the always-on deterministic layer from
[`scheduler/supervisor.py`](../scion/scheduler/supervisor.py): the **receiver** in
the foreground and the **cron scheduler** behind it as a supervised thread, each
**restarted on crash** with capped backoff. (`--no-telegram` / `--no-cron` drop a
half; with no token the receiver is skipped and cron holds the foreground.)
`scion tg receive` is just the receiver alone — handy for a quick test.

> **You also need the brain running.** The receiver only *queues* messages. Start a
> Claude Code session in this repo and run **`/loop scion autopilot`** (it follows
> [`MASTER_PROMPT.md`](../MASTER_PROMPT.md) and drains the queue forever). Without a
> `/loop` session, messages are acked as "queued" but **never answered** — they just
> pile up in the queue.

---

## 6. Built-in receiver commands

Any message starting with `/` is handled locally by the receiver; **everything else
is enqueued** for the brain. Non-text messages (photos, stickers, …) are ignored.

| Command | What it does |
|---|---|
| `/start`, `/help` | Greeting + "send me anything, it goes on the work queue." |
| `/status` | Live queue counts (e.g. `queue: {'pending': 2, 'done': 41}`, or `queue: empty`). |

Unknown slash commands get `Unknown command. Try /help.` These three are the whole
command surface — there's no inline session to reset, because there's no inline LLM.

---

## 7. Proactive messages

The bot doesn't only react — scion can reach out to your **default chat**
(`TELEGRAM_CHAT_ID`, from §2):

- **`scion tg send <chat_id> "…"`** — the brain's reply path, and also usable to push
  to any chat. Prints `sent`, or `send failed (token/chat configured?)`.
- **`notify(text)`** — the helper in `telegram.py`. Pushes one message to the
  **default chat**; a no-op (returns `False`) unless both token and chat id are set.
- **Cron-driven pings** — a scheduled job enqueues a task with no chat of its own;
  when the brain runs it, it can `notify(...)` or `scion tg send` the result into your
  default chat. Run `scion sentinel` (receiver + cron) plus a `/loop` session and your
  daily/interval jobs report into Telegram automatically.

---

## 8. Safety

- **Nothing to leak in the path.** There's no API key or model token in the Telegram
  request flow — the receiver just talks to Telegram and the local queue.
- **The allow-list is your main gate.** `TELEGRAM_ALLOWED_USER_IDS` decides who may
  queue work at all (§3). Set it before you expose the bot.
- **The brain decides what actually happens.** Queueing a message is not authority to
  act — the Claude Code session follows [`MASTER_PROMPT.md`](../MASTER_PROMPT.md),
  which holds it back from destructive or outward-facing actions (e.g. asking first
  when `SCION_CONFIRM_DANGEROUS=1`), on top of Claude Code's own permission prompts.

---

See the [README](../README.md) for the broader picture and
[`.env.example`](../.env.example) for every Telegram variable in context.
