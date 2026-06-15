# Telegram 🤖

scion treats **Telegram as a first-class channel**: a long-poll bot, built on
`urllib` with zero extra dependencies, that runs the agent inline and **streams
its replies into a single message** so you watch it think. This is the surface
you point your users at after you fork and grow a specialist.

Everything here lives in [`scion/channels/telegram.py`](../scion/channels/telegram.py).
Run `scion doctor` at any point — its **channels** section reports whether the
token is set and what `chat_id` it will use.

---

## 1. Create a bot and set the token

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, pick a name and a `@username`, and copy the **HTTP API token**
   it gives you (looks like `123456789:AAE…`).
3. Paste it into `.env`:

   ```bash
   TELEGRAM_BOT_TOKEN=123456789:AAE...your-token...
   ```

That's the only value you *must* set by hand. On startup the bot calls Telegram's
`getMe`; if the token is bad it fails loudly with `Telegram auth failed`.

---

## 2. chat-id auto-capture (you don't set it by hand)

Leave `TELEGRAM_CHAT_ID` **blank**. The **first message the bot receives** triggers
auto-capture: the bot reads the incoming `chat.id` and writes it back into `.env`
for you, so the next run already knows where "home" is.

The write-back is done by `set_env_var` in
[`scion/config.py`](../scion/config.py) — it create-or-updates the `TELEGRAM_CHAT_ID=`
line in `.env` *and* the live environment in one shot (the ali-fleet-recovery
trick). After your first "hi", you'll see the line populated:

```bash
TELEGRAM_CHAT_ID=987654321
```

This captured chat is the **default chat** for proactive pushes (see §8). To move
it to a different chat or group, clear the line and message the bot again.

---

## 3. The allow-list (set this before you expose the bot)

`TELEGRAM_ALLOWED_USER_IDS` is a **comma-separated list of numeric Telegram user
IDs** allowed to command the agent:

```bash
TELEGRAM_ALLOWED_USER_IDS=987654321,123123123
```

- **Empty (default) = anyone** who can message the bot may drive it. Fine for a
  private bot only you can reach; **strongly** lock it down for anything else.
- Set, and any other sender gets a flat `Not authorized.` reply.
- The check is **per user** (`message.from.id`), so it filters individuals even in
  a shared group chat. Separators may be commas or semicolons; non-numeric junk is
  ignored (`_list_int` in `config.py`).

**Finding your user id:** message [@userinfobot](https://t.me/userinfobot) (or
@RawDataBot) — it replies with your numeric `Id`. Put that number in the list.

---

## 4. Running it: `scion telegram` vs `scion serve`

```bash
scion telegram     # the bot, and only the bot
scion serve        # the bot in the foreground + the autonomy stack behind it
```

`scion telegram` runs **just the bot**: it long-polls for messages and runs the
agent **inline** with streaming replies, keeping **one session per chat** (so the
conversation has memory until you `/reset`). `scion serve` runs the **full
autonomy stack** from [`scheduler/supervisor.py`](../scion/scheduler/supervisor.py):
the same bot takes the foreground, while a **queue worker** (drains the durable
task queue) and the **cron scheduler** run behind it as supervised threads, each
**restarted on crash** with capped backoff. Use `scion telegram` for an
interactive chat bot; use `scion serve` when you want it unattended, draining
tasks and firing scheduled jobs. (`serve` accepts `--no-bot`, `--no-worker`,
`--no-scheduler`; with no token, the bot is skipped and the worker takes the
foreground.)

---

## 5. Built-in commands

Any message starting with `/` is handled locally; **everything else is sent
straight to the agent.**

| Command | What it does |
|---|---|
| `/start`, `/help` | Greeting + the command list. |
| `/status` | Tool count + task-queue counts (e.g. `tools: 33` / `queue: empty`). |
| `/reset` | Drops this chat's session and starts a **fresh** one. |

Unknown slash commands get `Unknown command. Try /help.` Non-text messages
(photos, stickers, …) are ignored.

---

## 6. Streaming UX

When you send a normal message, the bot first posts a `…` placeholder, then
**edits that one message in place** as the agent's text streams in — the
`StreamEditor`. Edits are **throttled** (it only re-edits after ~80 new characters
*and* at least ~1.2s have passed) to stay well under Telegram's flood limits while
still feeling live.

On completion the message is finalized with the full reply. Replies longer than
**4096 characters** (`MAX_LEN`) overflow into follow-up messages: the first 4096
chars stay in the edited message, the remainder is sent as additional chunks.
Outgoing sends use Markdown with an automatic **plain-text fallback** if Telegram
rejects the formatting.

---

## 7. Safety: confirmation is DISABLED over Telegram by default

This is the one caveat to internalize before you trust the bot with anything
destructive.

`TelegramChannel.can_confirm = False`. The agent loop reads that flag into the
risk policy as `can_ask=False` (see [`agent/loop.py`](../scion/agent/loop.py) and
[`security/policy.py`](../scion/security/policy.py)). Per that policy, a
**`dangerous`-risk tool** (e.g. `publish_changes`) with no operator available to
confirm and `require_confirmation` on is **denied** — the agent gets back
*"Refused: … is high-risk and no operator is available to confirm it."* `safe` and
`moderate` tools run as normal.

So, over Telegram, by default:

- **`safe` / `moderate` tools run.** Most work proceeds fine.
- **`dangerous` tools are denied** unless you set:

  ```bash
  SCION_REQUIRE_CONFIRMATION=0
  ```

  which lets dangerous tools run **unattended, with no approval step** — only do
  this when you fully trust the setup (recall secrets are masked and the publisher
  hard-aborts on staged secrets, but a denied gate is your last human checkpoint).

The tradeoff is deliberate: a streamed bot has no clean place to block the loop on
a yes/no. **Inline-button confirmation** (Telegram already exposes the pieces —
`buttons` on `send_message`, `answer_callback`, and `callback_query` updates) is a
**documented extension point**: wire `TelegramChannel.confirm` to post an approve/
deny keyboard and flip `can_confirm` to `True`.

---

## 8. Proactive messages

The bot doesn't only react — scion can reach out to your **default chat**
(`TELEGRAM_CHAT_ID`, from §2):

- **`notify(text)`** — the helper in `telegram.py`. Pushes one message to the
  default chat; a no-op (returns `False`) unless both token and chat id are set.
  Use it for alerts and "done" pings.
- **Worker replies** — when the queue worker finishes a task it sends the result
  back to the task's **originating chat** if one was recorded, otherwise it falls
  back to the **default chat** ([`scheduler/worker.py`](../scion/scheduler/worker.py)).
- **Cron results** — scheduled jobs enqueue tasks with no chat of their own, so
  their output lands in the **default chat**. Run `scion serve` (worker + scheduler
  + bot together) and your daily/interval jobs report into Telegram automatically.

---

See the [README](../README.md) for the broader picture and
[`.env.example`](../.env.example) for every Telegram variable in context.
