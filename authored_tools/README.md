# authored_tools/

Tools the agent has written for itself live here, one `.py` file per tool. They
are **hot-loaded by path** at startup (and immediately after the agent authors
one) and are **version-controlled** — `scion publish` commits this directory so
the agent's growing capability is durable, reviewable, and rollback-able.

Each file is a normal module that defines one or more `@tool`-decorated functions
(scion adds the decoration automatically when the agent writes a bare function).
You can also drop your own hand-written tools here — same contract as the
built-ins under `scion/tools/builtins/`.

Pending drafts (validated but not yet activated) live under
`workspace/tool_drafts/` until approved with `scion tool approve <name>` or
auto-applied when `SCION_TOOL_AUTOAPPLY=1`.
