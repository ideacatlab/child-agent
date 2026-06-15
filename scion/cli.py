"""``scion`` command-line interface."""

from __future__ import annotations

import argparse
import sys

from scion import __version__
from scion.config import get_settings
from scion.logging import configure, get_logger

log = get_logger("cli")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


def _ok(label: str, detail: str = "") -> None:
    print(f"  \033[32m✓\033[0m {label}" + (f" — {detail}" if detail else ""))


def _warn(label: str, detail: str = "") -> None:
    print(f"  \033[33m!\033[0m {label}" + (f" — {detail}" if detail else ""))


def _have(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_doctor(_args) -> int:
    s = get_settings()
    _section("scion " + __version__)
    print(f"  workspace: {s.workspace}")
    print(f"  model: {s.model}  effort: {s.effort}  thinking: {s.thinking}")
    print(f"  autonomous: {s.autonomous}  confirm: {s.require_confirmation}  "
          f"self-tooling: {s.allow_self_tooling} (autoapply: {s.tool_autoapply})")
    print(f"  embeddings: {s.embedding_backend}")

    _section("LLM")
    if _have("anthropic"):
        _ok("anthropic SDK installed")
    else:
        _warn("anthropic SDK missing", "pip install anthropic")
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        _ok("ANTHROPIC_API_KEY set")
    else:
        _warn("ANTHROPIC_API_KEY not set", "the agent can't call Claude without it")

    _section("optional dependencies")
    for label, mod in [
        ("requests (web)", "requests"),
        ("numpy (faster vectors)", "numpy"),
        ("pypdf (PDF ingest)", "pypdf"),
        ("beautifulsoup4 (HTML)", "bs4"),
        ("sentence-transformers", "sentence_transformers"),
        ("voyageai", "voyageai"),
        ("openai", "openai"),
    ]:
        (_ok if _have(mod) else _warn)(label, "" if _have(mod) else "not installed")

    _section("subsystems")
    try:
        from scion.tools.registry import get_registry

        reg = get_registry()
        _ok("tools", f"{len(reg)} registered")
    except Exception as exc:
        _warn("tools failed to load", str(exc))
    try:
        from scion.queue.task_queue import get_queue

        _ok("task queue", str(get_queue().counts() or "empty"))
    except Exception as exc:
        _warn("queue error", str(exc))
    try:
        from scion.rag.store import get_store

        _ok("knowledge base", str(get_store().stats()))
    except Exception as exc:
        _warn("rag error", str(exc))

    _section("channels")
    if s.telegram_bot_token:
        _ok("telegram token set", f"chat_id={s.telegram_chat_id or 'will auto-capture'}")
    else:
        _warn("telegram not configured", "set TELEGRAM_BOT_TOKEN to enable the bot")
    if s.git_remote:
        _ok("git remote set", s.git_remote)
    else:
        _warn("no git remote", "set SCION_GIT_REMOTE to enable self-publish push")
    print()
    return 0


def cmd_run(args) -> int:
    from scion.agent.loop import AgentLoop
    from scion.channels.base import CLIChannel

    channel = CLIChannel(assume_yes=args.yes)
    loop = AgentLoop()
    loop.run(
        args.prompt,
        channel=channel,
        autonomous=args.autonomous,
        on_text=lambda t: (sys.stdout.write(t), sys.stdout.flush()),
    )
    print()
    return 0


def cmd_chat(args) -> int:
    from scion.agent.loop import AgentLoop
    from scion.agent.session import Session
    from scion.channels.base import CLIChannel

    channel = CLIChannel(assume_yes=args.yes)
    loop = AgentLoop()
    session = Session.new("cli")
    print(f"{get_settings().agent_name} — chat (Ctrl-D to exit)\n")
    while True:
        try:
            user = input("\033[1myou>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user:
            continue
        if user in ("/exit", "/quit"):
            return 0
        if user == "/reset":
            session = Session.new("cli")
            print("(new session)")
            continue
        sys.stdout.write("\033[1mscion>\033[0m ")
        loop.run(user, session=session, channel=channel,
                 on_text=lambda t: (sys.stdout.write(t), sys.stdout.flush()))
        print("\n")


def cmd_task(args) -> int:
    from scion.queue.task_queue import get_queue

    q = get_queue()
    if args.task_cmd == "add":
        tid, is_new = q.add(args.text, kind=args.kind, source="cli", priority=args.priority)
        print(f"queued task #{tid}" + ("" if is_new else " (already queued)"))
    elif args.task_cmd == "list":
        for t in q.recent(limit=args.limit, status=args.status or None):
            print(f"#{t.id} [{t.status}] {t.kind} p{t.priority}: {t.text[:80]}")
        print("counts:", q.counts() or "empty")
    elif args.task_cmd == "work":
        from scion.scheduler.worker import Worker

        Worker().run(once=args.once)
    return 0


def cmd_tool(args) -> int:
    from scion.tools.registry import get_registry

    reg = get_registry()
    if args.tool_cmd == "list":
        for t in sorted(reg.all(), key=lambda x: (x.source, x.name)):
            summary = (t.description or t.name).splitlines()[0][:60]
            print(f"{t.name:24} [{t.risk:9}] ({t.source}) {summary}")
    elif args.tool_cmd == "show":
        t = reg.get(args.name)
        if not t:
            print("no such tool")
            return 1
        import json

        print(json.dumps(t.to_anthropic(), indent=2))
    elif args.tool_cmd == "approve":
        from scion.tools.authoring import promote

        try:
            names = promote(args.name)
            print("activated:", ", ".join(names))
        except FileNotFoundError as exc:
            print(exc)
            return 1
    return 0


def cmd_skill(args) -> int:
    from scion.skills.loader import get_skills

    lib = get_skills(fresh=True)
    if args.skill_cmd == "list":
        print(lib.index() or "(no skills)")
    elif args.skill_cmd == "show":
        sk = lib.get(args.name)
        print(sk.body() if sk else "no such skill")
    return 0


def cmd_rag(args) -> int:
    if args.rag_cmd == "ingest":
        from scion.rag.pipeline import get_pipeline

        stats = get_pipeline().ingest_path(args.path, collection=args.collection)
        print(f"ingested into '{args.collection}': {stats}")
    elif args.rag_cmd == "search":
        from scion.rag.retrieve import search

        for r in search(args.query, collection=args.collection, k=args.k):
            print(f"\n{r.cite()} (score {r.score})\n{r.text[:600]}")
    elif args.rag_cmd == "stats":
        from scion.rag.store import get_store

        print(get_store().stats())
    return 0


def cmd_memory(args) -> int:
    from scion.memory.store import get_memory

    mem = get_memory()
    if args.memory_cmd == "show":
        print("# SOUL\n" + mem.soul())
        print("\n# USER\n" + mem.user())
        print("\n# MEMORY\n" + mem.memory())
        print("\n# CORE BLOCKS\n" + mem.blocks.render())
    elif args.memory_cmd == "search":
        for src, line in mem.search(args.query):
            print(f"[{src}] {line}")
    return 0


def cmd_cron(args) -> int:
    from scion.scheduler.cron import get_scheduler

    sched = get_scheduler()
    if args.cron_cmd == "list":
        for j in sched.list_jobs():
            import time

            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(j.next_run))
            print(f"{j.name}: {j.kind} {j.spec} next={when} -> {j.text[:50]}")
    elif args.cron_cmd == "add-interval":
        sched.add_interval(args.name, args.every, args.text)
        print(f"added interval job {args.name} every {args.every}")
    elif args.cron_cmd == "add-daily":
        sched.add_daily(args.name, args.at, args.text)
        print(f"added daily job {args.name} at {args.at}")
    elif args.cron_cmd == "remove":
        print("removed" if sched.remove(args.name) else "no such job")
    return 0


def cmd_telegram(_args) -> int:
    from scion.channels.telegram import TelegramBot

    TelegramBot().run()
    return 0


def cmd_serve(args) -> int:
    from scion.scheduler.supervisor import serve

    serve(bot=not args.no_bot, worker=not args.no_worker, scheduler=not args.no_scheduler)
    return 0


def cmd_publish(args) -> int:
    from scion.publish.git_publish import get_publisher

    print(get_publisher().publish(args.message))
    return 0


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="scion", description="self-improving generalist Claude agent")
    p.add_argument("--version", action="version", version=f"scion {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check configuration and dependencies").set_defaults(func=cmd_doctor)

    pr = sub.add_parser("run", help="run the agent once on a prompt")
    pr.add_argument("prompt")
    pr.add_argument("--autonomous", action="store_true", help="don't pause for confirmation")
    pr.add_argument("--yes", action="store_true", help="auto-approve risky tools")
    pr.set_defaults(func=cmd_run)

    pc = sub.add_parser("chat", help="interactive chat with the agent")
    pc.add_argument("--yes", action="store_true", help="auto-approve risky tools")
    pc.set_defaults(func=cmd_chat)

    pt = sub.add_parser("task", help="task queue operations")
    tsub = pt.add_subparsers(dest="task_cmd", required=True)
    ta = tsub.add_parser("add")
    ta.add_argument("text")
    ta.add_argument("--kind", default="chat")
    ta.add_argument("--priority", type=int, default=0)
    tl = tsub.add_parser("list")
    tl.add_argument("--status", default="")
    tl.add_argument("--limit", type=int, default=20)
    tw = tsub.add_parser("work")
    tw.add_argument("--once", action="store_true")
    pt.set_defaults(func=cmd_task)

    ptool = sub.add_parser("tool", help="inspect / approve tools")
    tosub = ptool.add_subparsers(dest="tool_cmd", required=True)
    tosub.add_parser("list")
    tos = tosub.add_parser("show")
    tos.add_argument("name")
    toa = tosub.add_parser("approve")
    toa.add_argument("name")
    ptool.set_defaults(func=cmd_tool)

    psk = sub.add_parser("skill", help="list / show skills")
    sksub = psk.add_subparsers(dest="skill_cmd", required=True)
    sksub.add_parser("list")
    sks = sksub.add_parser("show")
    sks.add_argument("name")
    psk.set_defaults(func=cmd_skill)

    prag = sub.add_parser("rag", help="ingest / search the knowledge base")
    rsub = prag.add_subparsers(dest="rag_cmd", required=True)
    ri = rsub.add_parser("ingest")
    ri.add_argument("path")
    ri.add_argument("--collection", default="default")
    rs = rsub.add_parser("search")
    rs.add_argument("query")
    rs.add_argument("--collection", default="default")
    rs.add_argument("-k", type=int, default=6)
    rsub.add_parser("stats")
    prag.set_defaults(func=cmd_rag)

    pm = sub.add_parser("memory", help="show / search memory")
    msub = pm.add_subparsers(dest="memory_cmd", required=True)
    msub.add_parser("show")
    ms = msub.add_parser("search")
    ms.add_argument("query")
    pm.set_defaults(func=cmd_memory)

    pcron = sub.add_parser("cron", help="scheduled jobs")
    csub = pcron.add_subparsers(dest="cron_cmd", required=True)
    csub.add_parser("list")
    ci = csub.add_parser("add-interval")
    ci.add_argument("name")
    ci.add_argument("every", help="e.g. 30m, 2h, 1d")
    ci.add_argument("text")
    cd = csub.add_parser("add-daily")
    cd.add_argument("name")
    cd.add_argument("at", help="HH:MM")
    cd.add_argument("text")
    cr = csub.add_parser("remove")
    cr.add_argument("name")
    pcron.set_defaults(func=cmd_cron)

    sub.add_parser("telegram", help="run the Telegram bot").set_defaults(func=cmd_telegram)

    ps = sub.add_parser("serve", help="run worker + scheduler + bot (autonomy stack)")
    ps.add_argument("--no-bot", action="store_true")
    ps.add_argument("--no-worker", action="store_true")
    ps.add_argument("--no-scheduler", action="store_true")
    ps.set_defaults(func=cmd_serve)

    pp = sub.add_parser("publish", help="commit + push the agent's changes")
    pp.add_argument("message")
    pp.set_defaults(func=cmd_publish)

    return p


def main(argv: list[str] | None = None) -> int:
    get_settings()  # loads .env, ensures dirs
    configure(get_settings().logs_dir)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        log.error("%s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
