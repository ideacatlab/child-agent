"""``agent`` command-line interface — the surface Claude Code drives.

There is no ``chat``/``run`` here: the brain is your Claude Code session looping
over ``agent autopilot`` as the **orchestrator**. These commands are the durable
infrastructure it calls — the queue, the **fleet** (spawn/measure/improve worker and
supervisor agents), **evolve** (git-backed self-rewrite), Telegram, retrieval,
memory, knowledge, tools, and publish.
"""

from __future__ import annotations

import json
import sys

from agent import __version__
from agent.config import get_settings
from agent.logging import configure, get_logger

log = get_logger("cli")


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
# autopilot — the single command the /loop master prompt calls each cycle
# --------------------------------------------------------------------------- #
def cmd_autopilot(_args) -> int:
    from agent.queue.task_queue import get_queue

    q = get_queue()
    q.requeue_stuck()
    task = q.claim_next()
    if task is None:
        print("IDLE — the work queue is empty. Nothing to do this cycle.")
        print(f"counts: {q.counts() or 'empty'}")
        return 0
    origin = task.origin or {}
    print(f"=== TASK #{task.id} (kind={task.kind}, source={task.source}) ===")
    if origin.get("who"):
        print(f"from: {origin['who']}")
    print()
    print(task.text)
    print()
    print("--- when finished ---")
    if origin.get("channel") == "telegram" and origin.get("chat_id") is not None:
        print(f'  reply:  agent tg send {origin["chat_id"]} "<your reply>"')
    print(f'  close:  agent task done {task.id} --result "<one-line summary>"')
    print(f'  or:     agent task fail {task.id} --error "<why>"   (it will retry)')
    return 0


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def cmd_doctor(_args) -> int:
    s = get_settings()
    _section("agent " + __version__ + "  (brain = your Claude Code subscription; no API, no token cost)")
    print(f"  workspace: {s.workspace}")
    print(f"  embeddings: {s.embedding_backend}   confirm_dangerous: {s.confirm_dangerous}   "
          f"allow_publish: {s.allow_publish}")

    _section("optional dependencies (core needs none)")
    for label, mod in [
        ("requests (web tools)", "requests"),
        ("numpy (faster vectors)", "numpy"),
        ("pypdf (PDF ingest)", "pypdf"),
        ("beautifulsoup4 (HTML)", "bs4"),
        ("sentence-transformers (local semantic embeddings)", "sentence_transformers"),
    ]:
        (_ok if _have(mod) else _warn)(label, "" if _have(mod) else "not installed")

    _section("subsystems")
    try:
        from agent.queue.task_queue import get_queue

        _ok("task queue", str(get_queue().counts() or "empty"))
    except Exception as exc:
        _warn("queue error", str(exc))
    try:
        from agent.rag.store import get_store

        _ok("knowledge base", str(get_store().stats()))
    except Exception as exc:
        _warn("rag error", str(exc))
    from agent.tools.authoring import list_authored

    _ok("authored tools", str(len(list_authored())))

    _section("fleet (spawned worker / supervisor agents)")
    import shutil

    claude_path = shutil.which(s.claude_bin)
    (_ok if claude_path else _warn)(
        "claude binary",
        claude_path or f"'{s.claude_bin}' not on PATH — workers can't spawn (set AGENT_CLAUDE_BIN)")
    try:
        from agent.fleet import get_metrics, get_registry

        reg = get_registry(fresh=True)
        (_ok if reg.names() else _warn)("agent roles", ", ".join(reg.names()) or "none in agents/")
        agg = get_metrics().aggregate()
        _ok("recorded runs", str(sum(a["total"] for a in agg)) if agg else "0")
    except Exception as exc:
        _warn("fleet error", str(exc))
    print(f"  identity: {s.agent_name or '(unnamed — set AGENT_NAME)'}   "
          f"permission_mode: {s.fleet_permission_mode}   "
          f"supervise_every: {s.supervise_every or 'off'}")

    _section("channels")
    (_ok if s.telegram_bot_token else _warn)(
        "telegram", f"chat_id={s.telegram_chat_id or 'will auto-capture'}" if s.telegram_bot_token
        else "set TELEGRAM_BOT_TOKEN to enable")
    (_ok if s.git_remote else _warn)("git remote", s.git_remote or "set AGENT_GIT_REMOTE to push")

    _section("start the runtime")
    print("  1) run the daemon (always-on, no LLM):     agent daemon")
    print("  2) open Claude Code and run the loop:       /loop agent autopilot")
    print(f"     (master prompt: {s.root / 'MASTER_PROMPT.md'})")
    print()
    return 0


# --------------------------------------------------------------------------- #
# task queue
# --------------------------------------------------------------------------- #
def cmd_task(args) -> int:
    from agent.queue.task_queue import get_queue

    q = get_queue()
    if args.task_cmd == "add":
        tid, is_new = q.add(args.text, kind=args.kind, source="cli", priority=args.priority)
        print(f"queued task #{tid}" + ("" if is_new else " (already queued)"))
    elif args.task_cmd == "next":
        task = q.claim_next() if args.claim else (q.pending(1) or [None])[0]
        print(json.dumps(
            {"empty": True} if task is None else
            {"id": task.id, "kind": task.kind, "source": task.source,
             "text": task.text, "origin": task.origin, "priority": task.priority},
            indent=2))
    elif args.task_cmd == "done":
        q.complete(args.id, args.result or "")
        print(f"task #{args.id} done")
    elif args.task_cmd == "fail":
        q.fail(args.id, args.error or "")
        print(f"task #{args.id} marked failed (will retry up to 3x)")
    elif args.task_cmd == "list":
        for t in q.recent(limit=args.limit, status=args.status or None):
            print(f"#{t.id} [{t.status}] {t.kind} p{t.priority}: {t.text[:80]}")
        print("counts:", q.counts() or "empty")
    elif args.task_cmd == "gc":
        print(f"obsoleted {q.gc()} stale item(s)")
    return 0


# --------------------------------------------------------------------------- #
# telegram
# --------------------------------------------------------------------------- #
def cmd_tg(args) -> int:
    from agent.channels.telegram import send

    if args.tg_cmd == "send":
        ok = send(args.chat_id, args.text)
        print("sent" if ok else "send failed (token/chat configured?)")
        return 0 if ok else 1
    if args.tg_cmd == "receive":
        from agent.channels.telegram import TelegramReceiver

        TelegramReceiver().run()
    return 0


def cmd_daemon(args) -> int:
    from agent.scheduler.daemon import run_daemon

    run_daemon(
        telegram=not args.no_telegram,
        cron=not args.no_cron,
        supervise=not args.no_supervise,
    )
    return 0


# --------------------------------------------------------------------------- #
# rag / memory / knowledge / skills / tools / publish / cron
# --------------------------------------------------------------------------- #
def cmd_rag(args) -> int:
    if args.rag_cmd == "ingest":
        from agent.rag.pipeline import get_pipeline

        print(f"ingested into '{args.collection}': "
              f"{get_pipeline().ingest_path(args.path, collection=args.collection)}")
    elif args.rag_cmd == "search":
        from agent.rag.retrieve import search

        for r in search(args.query, collection=args.collection, k=args.k):
            print(f"\n{r.cite()} (score {r.score})\n{r.text[:600]}")
    elif args.rag_cmd == "stats":
        from agent.rag.store import get_store

        print(get_store().stats())
    return 0


def cmd_memory(args) -> int:
    from agent.memory.store import get_memory

    mem = get_memory()
    if args.memory_cmd == "show":
        print("# IDENTITY\n" + mem.identity() + "\n\n# USER\n" + mem.user() + "\n\n# MEMORY\n" + mem.memory())
        print("\n# CORE BLOCKS\n" + mem.blocks.render())
    elif args.memory_cmd == "search":
        for src, line in mem.search(args.query):
            print(f"[{src}] {line}")
    elif args.memory_cmd == "remember":
        print(mem.remember(args.fact))
    elif args.memory_cmd == "journal":
        print(mem.journal(args.note))
    elif args.memory_cmd == "user":
        print(mem.update_user(args.note))
    elif args.memory_cmd == "recent":
        print(mem.recent_journal())
    return 0


def cmd_know(args) -> int:
    from agent.knowledge import KnowledgeRegistry

    reg = KnowledgeRegistry()
    if args.know_cmd == "note":
        print("recorded " + reg.note(args.title, args.detail, args.status))
    elif args.know_cmd == "list":
        print(reg.listing())
    return 0


def cmd_skill(args) -> int:
    from agent.skills.loader import get_skills

    lib = get_skills(fresh=True)
    if args.skill_cmd == "list":
        print(lib.index() or "(no skills)")
    elif args.skill_cmd == "show":
        sk = lib.get(args.name)
        print(sk.body() if sk else "no such skill")
    return 0


def cmd_tool(args) -> int:
    from agent.tools.authoring import list_authored, list_drafts, promote, scaffold, validate

    if args.tool_cmd == "new":
        path = scaffold(args.name, args.description or "")
        print(f"scaffolded draft: {path}\nimplement it, then: agent tool validate {args.name}")
    elif args.tool_cmd == "validate":
        s = get_settings()
        path = s.drafts_dir / f"{args.name}.py"
        if not path.exists():
            path = s.authored_tools_dir / f"{args.name}.py"
        print(validate(path).render())
    elif args.tool_cmd == "approve":
        s = get_settings()
        res = validate(s.drafts_dir / f"{args.name}.py")
        if not res.ok:
            print("refused — validation failed:\n" + res.render())
            return 1
        print(f"promoted: {promote(args.name)}")
    elif args.tool_cmd == "list":
        for name, summary in list_authored():
            print(f"{name:24} {summary}")
        drafts = list_drafts()
        if drafts:
            print("drafts (pending):", ", ".join(drafts))
    return 0


def cmd_publish(args) -> int:
    from agent.publish.git_publish import get_publisher

    if args.publish_cmd == "status":
        print(get_publisher().status() or "(clean working tree)")
    else:  # commit
        print(get_publisher().publish(args.message))
    return 0


def cmd_cron(args) -> int:
    import time

    from agent.scheduler.cron import get_scheduler

    sched = get_scheduler()
    if args.cron_cmd == "list":
        for j in sched.list_jobs():
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
    elif args.cron_cmd == "run":
        print(f"fired {sched.tick()} due job(s)")
    return 0


# --------------------------------------------------------------------------- #
# fleet — spawn / measure / improve worker & supervisor agents
# --------------------------------------------------------------------------- #
def cmd_fleet(args) -> int:
    from dataclasses import asdict

    from agent.fleet import (
        get_metrics, get_registry, reap, run_worker, spawn_worker, supervise_once,
    )

    cmd = args.fleet_cmd
    if cmd == "roles":
        print(get_registry(fresh=True).index() or "(no agent roles in agents/)")
    elif cmd == "run":
        r = run_worker(args.role, args.task, model=args.model)
        print(f"run #{r.id} [{r.status}] {r.role}\n{r.summary or ''}")
        return 0 if r.status == "ok" else 1
    elif cmd == "spawn":
        r = spawn_worker(args.role, args.task, model=args.model)
        print(f"spawned run #{r.id} [{r.status}] {r.role} "
              f"(pid {r.pid}); check it with `agent fleet status`")
        return 0 if r.status != "error" else 1
    elif cmd == "status":
        reap()
        m = get_metrics()
        if args.run_id:
            r = m.get(args.run_id)
            if not r:
                print("no such run"); return 1
            print(json.dumps(asdict(r), indent=2))
        else:
            rows = m.recent(limit=args.limit)
            for r in rows:
                dur = f"{r.duration_ms / 1000:.1f}s" if r.duration_ms else "-"
                print(f"#{r.id} [{r.status}] {r.role} {dur}: {(r.summary or r.prompt)[:70]}")
            if not rows:
                print("(no runs yet)")
    elif cmd == "logs":
        from pathlib import Path

        r = get_metrics().get(args.run_id)
        if not r or not r.log_path:
            print("no log for that run"); return 1
        p = Path(r.log_path)
        print(p.read_text(encoding="utf-8", errors="replace") if p.exists() else "(log file missing)")
    elif cmd == "new":
        path = get_registry().scaffold(args.role, args.description or "")
        print(f"wrote new agent role: {path}\n"
              f'edit its charter, then: agent fleet run {args.role} "<task>"')
    elif cmd == "metrics":
        m = get_metrics()
        if args.role:
            print(json.dumps(m.aggregate(args.role), indent=2))
        else:
            print(m.digest())
    elif cmd == "supervise":
        r = supervise_once()
        if r is None:
            print("no supervisor role defined (agents/supervisor/AGENT.md)"); return 1
        print(f"supervision run #{r.id} [{r.status}]\n{r.summary or ''}")
        return 0 if r.status == "ok" else 1
    return 0


# --------------------------------------------------------------------------- #
# evolve — git-backed, unrestricted self-rewrite
# --------------------------------------------------------------------------- #
def cmd_evolve(args) -> int:
    from agent import evolve

    cmd = args.evolve_cmd
    if cmd == "checkpoint":
        print(evolve.checkpoint(args.label))
    elif cmd == "diff":
        print(evolve.diff(args.ref))
    elif cmd == "revert":
        print(evolve.revert(args.ref))
    elif cmd == "log":
        print(evolve.log(args.limit))
    return 0


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser():
    import argparse

    p = argparse.ArgumentParser(
        prog="agent",
        description="durable infrastructure for a self-rewriting, multi-agent Claude Code runtime")
    p.add_argument("--version", action="version", version=f"agent {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check configuration + dependencies + the fleet").set_defaults(func=cmd_doctor)
    sub.add_parser("autopilot", help="claim & print the next task (the /loop entrypoint)").set_defaults(func=cmd_autopilot)

    pt = sub.add_parser("task", help="task queue")
    ts = pt.add_subparsers(dest="task_cmd", required=True)
    a = ts.add_parser("add"); a.add_argument("text"); a.add_argument("--kind", default="chat"); a.add_argument("--priority", type=int, default=0)
    n = ts.add_parser("next"); n.add_argument("--claim", action="store_true")
    d = ts.add_parser("done"); d.add_argument("id", type=int); d.add_argument("--result", default="")
    fa = ts.add_parser("fail"); fa.add_argument("id", type=int); fa.add_argument("--error", default="")
    ln = ts.add_parser("list"); ln.add_argument("--status", default=""); ln.add_argument("--limit", type=int, default=20)
    ts.add_parser("gc")
    pt.set_defaults(func=cmd_task)

    ptg = sub.add_parser("tg", help="telegram send / receive")
    tgs = ptg.add_subparsers(dest="tg_cmd", required=True)
    snd = tgs.add_parser("send"); snd.add_argument("chat_id"); snd.add_argument("text")
    tgs.add_parser("receive")
    ptg.set_defaults(func=cmd_tg)

    psent = sub.add_parser("daemon", help="run the always-on layer (telegram + cron + supervision)")
    psent.add_argument("--no-telegram", action="store_true")
    psent.add_argument("--no-cron", action="store_true")
    psent.add_argument("--no-supervise", action="store_true")
    psent.set_defaults(func=cmd_daemon)

    pf = sub.add_parser("fleet", help="spawn / measure / improve worker & supervisor agents")
    fs = pf.add_subparsers(dest="fleet_cmd", required=True)
    fs.add_parser("roles", help="list agent roles (agents/<role>/AGENT.md)")
    fr = fs.add_parser("run", help="spawn one worker, wait, print its result")
    fr.add_argument("role"); fr.add_argument("task"); fr.add_argument("--model", default=None)
    fsp = fs.add_parser("spawn", help="spawn a worker in the background, return its run id")
    fsp.add_argument("role"); fsp.add_argument("task"); fsp.add_argument("--model", default=None)
    fst = fs.add_parser("status", help="running / recent worker runs"); fst.add_argument("run_id", type=int, nargs="?"); fst.add_argument("--limit", type=int, default=20)
    fl = fs.add_parser("logs", help="a worker's captured output"); fl.add_argument("run_id", type=int)
    fn = fs.add_parser("new", help="scaffold a new agent role (write a new agent)"); fn.add_argument("role"); fn.add_argument("--description", default="")
    fm = fs.add_parser("metrics", help="per-agent performance"); fm.add_argument("role", nargs="?")
    fs.add_parser("supervise", help="run one supervision cycle (the always-on improver)")
    pf.set_defaults(func=cmd_fleet)

    pe = sub.add_parser("evolve", help="git-backed self-rewrite (checkpoint / diff / revert / log)")
    es = pe.add_subparsers(dest="evolve_cmd", required=True)
    ec = es.add_parser("checkpoint", help="commit current state before a rewrite"); ec.add_argument("label")
    ed = es.add_parser("diff", help="changes since the last checkpoint"); ed.add_argument("ref", nargs="?", default=None)
    erv = es.add_parser("revert", help="roll back to a checkpoint (discards uncommitted work)"); erv.add_argument("ref", nargs="?", default=None)
    el = es.add_parser("log", help="checkpoint / commit history"); el.add_argument("--limit", type=int, default=15)
    pe.set_defaults(func=cmd_evolve)

    prag = sub.add_parser("rag", help="ingest / search the knowledge base")
    rs = prag.add_subparsers(dest="rag_cmd", required=True)
    ri = rs.add_parser("ingest"); ri.add_argument("path"); ri.add_argument("--collection", default="default")
    rse = rs.add_parser("search"); rse.add_argument("query"); rse.add_argument("--collection", default="default"); rse.add_argument("-k", type=int, default=6)
    rs.add_parser("stats")
    prag.set_defaults(func=cmd_rag)

    pm = sub.add_parser("memory", help="memory: show / search / remember / journal")
    ms = pm.add_subparsers(dest="memory_cmd", required=True)
    ms.add_parser("show")
    msr = ms.add_parser("search"); msr.add_argument("query")
    mr = ms.add_parser("remember"); mr.add_argument("fact")
    mj = ms.add_parser("journal"); mj.add_argument("note")
    mu = ms.add_parser("user"); mu.add_argument("note")
    ms.add_parser("recent")
    pm.set_defaults(func=cmd_memory)

    pk = sub.add_parser("know", help="self-rendering knowledge registry")
    ks = pk.add_subparsers(dest="know_cmd", required=True)
    kn = ks.add_parser("note"); kn.add_argument("title"); kn.add_argument("detail"); kn.add_argument("--status", default="open")
    ks.add_parser("list")
    pk.set_defaults(func=cmd_know)

    psk = sub.add_parser("skill", help="list / show skills")
    sks = psk.add_subparsers(dest="skill_cmd", required=True)
    sks.add_parser("list")
    sksh = sks.add_parser("show"); sksh.add_argument("name")
    psk.set_defaults(func=cmd_skill)

    ptool = sub.add_parser("tool", help="author tool scripts (scaffold/validate/approve/list)")
    tos = ptool.add_subparsers(dest="tool_cmd", required=True)
    tn = tos.add_parser("new"); tn.add_argument("name"); tn.add_argument("--description", default="")
    tv = tos.add_parser("validate"); tv.add_argument("name")
    ta = tos.add_parser("approve"); ta.add_argument("name")
    tos.add_parser("list")
    ptool.set_defaults(func=cmd_tool)

    pp = sub.add_parser("publish", help="commit + push the agent's changes")
    pps = pp.add_subparsers(dest="publish_cmd", required=True)
    ppc = pps.add_parser("commit"); ppc.add_argument("message")
    pps.add_parser("status")
    pp.set_defaults(func=cmd_publish)

    pc = sub.add_parser("cron", help="scheduled jobs that enqueue work")
    cs = pc.add_subparsers(dest="cron_cmd", required=True)
    cs.add_parser("list")
    ci = cs.add_parser("add-interval"); ci.add_argument("name"); ci.add_argument("every"); ci.add_argument("text")
    cd = cs.add_parser("add-daily"); cd.add_argument("name"); cd.add_argument("at"); cd.add_argument("text")
    cr = cs.add_parser("remove"); cr.add_argument("name")
    cs.add_parser("run")
    pc.set_defaults(func=cmd_cron)

    return p


def main(argv: list[str] | None = None) -> int:
    get_settings()
    configure(get_settings().logs_dir)
    args = build_parser().parse_args(argv)
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
