# RAG — the knowledge base

> *"Hand me 200 PDFs and I'll become a marketer."*

That's the use case this subsystem is built for, and it's the one thing **plain
Claude Code cannot do on its own**. A client drops a folder of briefs, brand
guidelines, past campaigns, and contracts on the agent. Claude Code can't read 200
PDFs into context, but it *can* `agent rag search` across them and pull back only
the handful of passages that matter, **with citations**, instead of bluffing —
RAG's whole value-add over a bare Claude Code session.

The whole path runs on the **Python standard library** — no vector database, no
embedding service, no API key — so it works the moment you clone the repo. You
drive it through three CLI subcommands (`agent rag ingest`, `agent rag search`,
`agent rag stats`). The agent is itself a Claude Code session, so it calls those
**same subcommands from its shell**: there is no `rag_*` tool to register, and
nothing here ever touches an LLM API.

## A note on cost (read this first)

agent's whole reason to exist is **avoiding per-token cost** — the brain is your
flat Claude Code subscription, not a metered API. Retrieval honours that:

- **`hashing` (the default) is free.** A deterministic, zero-dependency
  feature-hashing bag-of-words embedder (`agent/rag/embeddings.py`). No package, no
  service, no key — it runs out of the box.
- **`sentence-transformers` (local) is also free.** Real semantic embeddings that
  run **on your machine**: a one-time model download, then no per-call cost.
- **`voyage` and `openai` are hosted and DO cost money** — they bill per request.
  They're the *only* place in agent that reintroduces a metered bill, so reach for
  them deliberately. (Voyage is Anthropic's suggested provider if you go hosted.)

**Why is the free default *local*, not "just use Anthropic"?** Because **Anthropic
has no embeddings endpoint** — Claude generates text, it doesn't turn text into
vectors. A free local default is the only zero-cost option; hosted is a paid opt-in.

## Ingesting documents

```bash
agent rag ingest <path> --collection <name>
```

- `<path>` is a single file **or a folder**. Folders are walked **recursively**
  (`rglob`) and every supported file under them is ingested in sorted order.
- `--collection` defaults to `default`. See [Collections](#collections).

**Supported file types** (`agent/rag/loaders.py`):

| Kind | Suffixes |
|---|---|
| Plain text / code | `.txt` `.md` `.markdown` `.rst` `.log` `.py` `.js` `.ts` `.csv` `.tsv` |
| PDF | `.pdf` |
| HTML | `.html` `.htm` |
| JSON | `.json` (pretty-printed before chunking) |

Anything else under a folder is silently skipped. `.md`/`.markdown` files are
chunked **header-aware** (split on `#`..`######`); everything else splits on
paragraph boundaries. Chunks default to ~1200 chars with 150 chars of overlap.

### PDFs need the `docs` extra

PDF extraction uses `pypdf`, which is **not** in the core install:

```bash
pip install -e ".[docs]"     # pypdf + beautifulsoup4 + lxml
```

It also pulls in `beautifulsoup4` for clean HTML-to-text; without it, HTML still
loads via a crude tag-stripping fallback, but PDF ingest errors out telling you to
install the extra.

### Re-ingesting only touches changed files (content-hash dedup)

Ingestion is an **upsert keyed by a content hash** (`agent/rag/pipeline.py`,
`agent/rag/store.py`): agent computes `sha256(content)` per document and compares it
to the stored hash for that file's absolute path. Unchanged → **skipped** (no
re-embedding, no writes). Changed → re-chunk, re-embed, and **replace** that
document's chunks (old deleted, new inserted) in one transaction.

Re-running after editing two files re-embeds only those two — cheap on a cron. Each
run prints an `IngestStats` line:

```
ingested into 'acme': added=2 updated=1 skipped=40 chunks=18 errors=0
```

`added` = new documents, `updated` = changed, `skipped` = unchanged (or empty /
unparseable), `chunks` = chunks written this run, `errors` = documents that failed
to load (logged, never fatal).

## Collections

A **collection** is a named, isolated index. Keep one topic or client per
collection so a search for client A never surfaces client B's documents:

```bash
agent rag ingest ./acme_corp   --collection acme
agent rag ingest ./globex_inc  --collection globex
```

Collections share one SQLite store but are filtered on every query, so they don't
bleed into each other. List what exists with `agent rag stats`.

The agent **chooses a collection per task** from context — your instructions, the
task text, or core memory ("the ACME work lives in the `acme` collection"). Tell it
which one, or record it in memory / `IDENTITY.md`.

## Searching

```bash
agent rag search "<query>" --collection <name> -k N
```

`--collection` defaults to `default`; `-k` is the number of chunks to return
(default `6`).

### The hybrid retriever

agent runs **two retrievers and fuses them** (`agent/rag/retrieve.py`):

1. **Dense** — cosine similarity between the query embedding and every stored chunk
   embedding (vectors are L2-normalized, so a dot product *is* cosine). The semantic
   leg; its quality tracks your embedding backend.
2. **BM25** — classic lexical ranking (TF × IDF, length-normalized, `k1=1.5`,
   `b=0.75`). The keyword leg; nails exact terms, names, and codes on any backend.
3. **Reciprocal-rank fusion (RRF)** — each leg ranks the chunks; a chunk's fused
   score is `Σ 1 / (60 + rank)` across both lists. No cross-scale calibration
   needed, which is why it's robust. Because BM25 always contributes, retrieval is
   useful **even on the default hashing backend** — real embeddings mainly sharpen
   the dense (semantic) leg.

### Results: citations + scores

Each result carries the chunk text, its source, and a fused score. Citations are
formatted `[path#chunk]` — the document path and the chunk's ordinal within that
document (`Result.cite()`) — so answers are auditable back to the exact passage:

```
[/home/you/acme_corp/refund-policy.md#2] (score 0.0328)
Refunds are issued to the original payment method within 14 business days...
```

The agent is told to lean on this: `MASTER_PROMPT.md` pairs `agent rag search` with
**"retrieve relevant chunks (cite them!)"** and a *Recall first* rule to search
before non-trivial work — so it grounds answers in cited chunks rather than guessing.

## Embedding backends

Set `AGENT_EMBEDDING_BACKEND` in `.env`. If the chosen backend's package or key is
missing, `get_embedder` **logs a warning and falls back to `hashing`** so retrieval
never hard-fails.

| `AGENT_EMBEDDING_BACKEND` | Install extra | Key | Cost | Dim | Default model |
|---|---|---|---|---|---|
| `hashing` *(default)* | none | none | **free** | `AGENT_EMBEDDING_DIM` (512) | — |
| `sentence-transformers` *(aliases `st`, `local`)* | `.[embeddings-local]` | none (local) | **free** | model-defined (384 for MiniLM) | `all-MiniLM-L6-v2` |
| `voyage` | `.[embeddings-voyage]` | `VOYAGE_API_KEY` | **paid (hosted)** | 1024 | `voyage-3` |
| `openai` | `.[embeddings-openai]` | `OPENAI_API_KEY` | **paid (hosted)** | 1536 | `text-embedding-3-small` |

```bash
# free, local semantic upgrade — no key, no per-call cost
pip install -e ".[embeddings-local]"
# in .env:  AGENT_EMBEDDING_BACKEND=sentence-transformers
```

Other knobs (`.env.example`):

- **`AGENT_EMBEDDING_MODEL`** — override the default model for the chosen backend
  (e.g. a different checkpoint, or `voyage-3-large`). Ignored by `hashing`.
- **`AGENT_EMBEDDING_DIM`** — vector size, and it **only matters for `hashing`**.
  The real backends report their own fixed dimension; this value does nothing there.

### Switching backends? Re-ingest.

Embeddings from different backends aren't comparable (different geometry, sometimes
different sizes), so after changing `AGENT_EMBEDDING_BACKEND` you must **re-embed
your corpus**. But a plain `agent rag ingest` **skips unchanged files** — dedup keys
on content, not on which embedder ran — so it won't refresh vectors on its own. To
force a clean rebuild, delete `workspace/vectors.db` and re-ingest, or use a fresh
`--collection`.

That `workspace/vectors.db` is the whole store (`docs` + `chunks` tables, embeddings
as JSON, `numpy` used if present). It's gitignored, so your corpus stays private;
`agent rag stats` reports `{'documents': N, 'chunks': N, 'collections': {...}}`.

## Worked example

```bash
# 1. (once) enable PDF + HTML ingest
pip install -e ".[docs]"

# 2. ingest a client's whole document folder into its own collection
agent rag ingest ./clients/acme --collection acme
# → ingested into 'acme': added=12 updated=0 skipped=0 chunks=204 errors=0

# 3. search it directly — exactly what the agent runs from its shell
agent rag search "what is the refund window?" --collection acme -k 3
#
# [/home/you/clients/acme/refund-policy.pdf#1] (score 0.0328)
# Customers may request a refund within 14 business days of purchase...
#
# [/home/you/clients/acme/faq.md#4] (score 0.0161)
# Q: How long do refunds take? A: Up to 14 business days...
```

Now give the running agent a task — `agent task add "Using the acme knowledge base,
what's their refund window? Cite it."` (or message it on Telegram). Its Claude Code
loop runs that same `agent rag search`, reads the top chunks, and answers grounded
in `[refund-policy.pdf#1]` instead of guessing — on your flat subscription, free
default embedder, no API key anywhere.
