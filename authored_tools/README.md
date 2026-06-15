# authored_tools/

Tools the agent has written for itself live here — one `.py` file per tool, each a
small **CLI script** (a usage docstring + an `argparse` interface) that the Claude
Code session runs via bash, e.g. `python authored_tools/business_days.py 2026-06-01
2026-06-15`. This is ali-fleet-recovery's "every tool is a script with a usage
docstring; the filesystem is the registry" convention.

They're **version-controlled** — `scion publish commit "…"` ships this directory,
so the agent's growing capability is durable, reviewable, and rollback-able. You
can hand-write tools here too; same contract.

Lifecycle:

```
scion tool new <name> --description "…"   # scaffold a draft (workspace/tool_drafts/)
# ...implement the script...
scion tool validate <name>                # syntax + structure + a --help smoke run
scion tool approve <name>                 # promote the validated draft here
scion tool list                           # what's available
```

A tool stays a *draft* under `workspace/tool_drafts/` until it validates and is
approved — a tool that won't even run `--help` never becomes "real."
