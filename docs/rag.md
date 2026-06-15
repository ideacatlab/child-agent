# RAG — the knowledge base

> *"Hand me 200 PDFs and I'll become a marketer."*

That's the use case this subsystem is built for. Drop a folder of a client's
briefs, brand guidelines, past campaigns, and contracts onto the agent, and it
can answer questions about them **with citations** instead of bluffing. The whole
retrieval path runs on the **Python standard library** — no vector database, no
embedding service, no API key — so it works the moment you clone the repo. When
you want better semantic quality, you flip one environment variable.

`scion/rag/` is a small pipeline: `loaders → chunkers → embeddings → store →
hybrid retrieve`. You touch it through three CLI commands (`scion rag
ingest|search|stats`) and three agent tools (`rag_ingest`, `rag_search`,
`rag_stats`).

---

## Why the default embedder is local

**Anthropic has no embeddings endpoint.** Claude generates text; it does not turn
text into vectors. So scion cannot lean on the one dependency it already requires
(`anthropic`) for retrieval, and it refuses to make a hosted embedding service a
hard requirement.

The default is therefore **`HashingEmbedder`** — a deterministic, zero-dependency
feature-hashing bag-of-words embedder (`scion/rag/embeddings.py`). It is not
*semantic*: it can't tell that "refund" and "money back" are related. But fused
with BM25 in the hybrid retriever (below) it gives solid **lexical** recall, and
it means the entire RAG stack works out of the box with nothing installed.

For real semantic search — synonyms, paraphrase, fuzzy intent — switch to a real
backend (`sentence-transformers`, `voyage`, or `openai`). **Voyage is Anthropic's
recommended embeddings partner.** See [Embedding backends](#embedding-backends).

---

## Ingesting documents

```bash
scion rag ingest <path> --collection <name>
```

- `<path>` is a single file **or a folder**. Folders are walked **recursively**
  (`rglob`), and every supported file under them is ingested in sorted order.
- `--collection` defaults to `default`. See [Collections](#collections).

**Supported file types** (`scion/rag/loaders.py`):

| Kind | Suffixes |
|---|---|
| Plain text / code | `.txt` `.md` `.markdown` `.rst` `.log` `.py` `.js` `.ts` `.csv` `.tsv` |
| PDF | `.pdf` |
| HTML | `.html` `.htm` |
| JSON | `.json` (pretty-printed before chunking) |

Anything else under a folder is silently skipped. `.md`/`.markdown` files are
chunked **header-aware** (sections split on `#`..`######`); everything else is
split on paragraph boundaries. Chunks are ~1200 chars with 150 chars of overlap
carried between them to preserve context.

### PDFs need the `docs` extra

PDF extraction uses `pypdf`, which is **not** part of the core install:

```bash
pip install -e ".[docs]"     # pypdf + beautifulsoup4 + lxml
```

The `docs` extra also pulls in `beautifulsoup4` for clean HTML-to-text. Without
it, HTML still loads via a crude tag-stripping fallback, but PDF ingest raises a
clear error telling you to install the extra.

### Re-ingesting only touches changed files (content-hash dedup)

Ingestion is an **upsert keyed by a content hash** (`scion/rag/pipeline.py`,
`scion/rag/store.py`). For each document scion:

1. loads the text and computes `sha256(content)`;
2. compares it to the stored hash for that document's absolute path;
3. **skips** the file if the hash is unchanged — no re-embedding, no writes;
4. otherwise re-chunks, re-embeds, and **replaces** that document's chunks
   (old chunks deleted, new ones inserted) in one transaction.

So re-running `scion rag ingest ./my_docs` after editing two files re-embeds only
those two. It's cheap to put on a cron. The run reports an `IngestStats` line:

```
ingested into 'acme': added=2 updated=1 skipped=40 chunks=18 errors=0
```

- **added** — documents seen for the first time
- **updated** — documents whose content changed
- **skipped** — unchanged (or empty / unparseable) documents
- **chunks** — chunks written this run
- **errors** — documents that failed to load (logged, never fatal)

---

## Collections

A **collection** is a named, isolated index. Keep one topic or client per
collection so a search for client A never surfaces client B's documents:

```bash
scion rag ingest ./acme_corp   --collection acme
scion rag ingest ./globex_inc  --collection globex
```

Collections live in the same SQLite store but are filtered on every query, so
they don't bleed into each other. List what exists with `scion rag stats`.

**How the agent picks a collection.** `rag_search`/`rag_ingest` take a
`collection` argument (default `"default"`). The agent chooses it from context —
the task, your instructions, or core memory ("the ACME work lives in the `acme`
collection"). If you want it to use a specific one, say so, or record it in
memory/`SOUL.md` so it's picked up automatically.

---

## Searching

```bash
scion rag search "<query>" --collection <name> -k N
```

- `--collection` defaults to `default`; `-k` is the number of chunks to return
  (default `6`).

### The hybrid retriever

scion runs **two retrievers and fuses them** (`scion/rag/retrieve.py`) — the
LlamaIndex/Haystack hybrid pattern:

1. **Dense** — cosine similarity between the query embedding and every stored
   chunk embedding (vectors are L2-normalized, so a dot product *is* cosine).
   This is the semantic leg; its quality depends on your embedding backend.
2. **BM25** — classic lexical ranking (term frequency × inverse document
   frequency, length-normalized). This is the keyword leg; it nails exact terms,
   names, and codes regardless of backend.
3. **Reciprocal-rank fusion (RRF)** — each leg produces a ranking; a chunk's
   fused score is `Σ 1 / (60 + rank)` across both lists. RRF needs no score
   calibration between the two very different scales, which is why it's robust.

Because BM25 always contributes, retrieval is useful **even on the default
hashing backend**. Switching to real embeddings mainly improves the dense leg.

### Results: citations + scores

Each result carries the chunk text, its source, and a fused score. Citations are
formatted `[path#ord]` — the document path and the chunk's ordinal within that
document — so answers are auditable back to the exact passage:

```
[/home/you/acme_corp/refund-policy.md#2] (score 0.0328)
Refunds are issued to the original payment method within 14 business days...
```

The agent is told to quote these citations rather than guess (see
[From the agent](#using-it-from-the-agent)).

---

## Embedding backends

Set `SCION_EMBEDDING_BACKEND` in `.env` (or as an env var). `get_embedder`
resolves it; if the chosen backend's package or key is missing, it **logs a
warning and falls back to `hashing`** so retrieval never hard-fails.

| `SCION_EMBEDDING_BACKEND` | Install extra | Key | Dim | Default model |
|---|---|---|---|---|
| `hashing` *(default)* | none | none | `SCION_EMBEDDING_DIM` (512) | — |
| `sentence-transformers` *(aliases `st`, `local`)* | `.[embeddings-local]` | none — runs locally | model-defined (384 for MiniLM) | `all-MiniLM-L6-v2` |
| `voyage` | `.[embeddings-voyage]` | `VOYAGE_API_KEY` | 1024 | `voyage-3` |
| `openai` | `.[embeddings-openai]` | `OPENAI_API_KEY` | 1536 | `text-embedding-3-small` |

```bash
# example: hosted Voyage embeddings (Anthropic's recommended partner)
pip install -e ".[embeddings-voyage]"
# in .env:
#   SCION_EMBEDDING_BACKEND=voyage
#   VOYAGE_API_KEY=...
```

Other knobs (`.env.example`):

- **`SCION_EMBEDDING_MODEL`** — override the default model for the chosen backend
  (e.g. a different sentence-transformers checkpoint or `voyage-3-large`). Ignored
  by `hashing`.
- **`SCION_EMBEDDING_DIM`** — vector size, and it **only matters for the `hashing`
  backend**. The real backends report their own fixed dimension; this value does
  nothing for them.

### Switching backends? Re-ingest.

Embeddings from different backends are not comparable — different geometry,
different (and sometimes different-sized) vectors. After changing
`SCION_EMBEDDING_BACKEND` you should **re-embed your corpus**.

Note the subtlety: a plain `scion rag ingest` will **skip unchanged files**
(content-hash dedup is about content, not about which embedder produced the
stored vectors), so re-running it alone won't refresh the embeddings. To force a
clean rebuild, either:

- delete the store at `workspace/vectors.db` and re-ingest, **or**
- ingest into a **fresh `--collection`** and search that one instead.

---

## Using it from the agent

The same pipeline is exposed as three built-in tools
(`scion/tools/builtins/rag_tools.py`):

| Tool | Risk | What it does |
|---|---|---|
| `rag_ingest(path, collection="default")` | `moderate` | Ingest a file/folder into a collection. |
| `rag_search(query, collection="default", k=6)` | `safe` | Return the top-`k` chunks with citations + scores. |
| `rag_stats()` | `safe` | Report documents, chunks, and collections. |

`rag_search` and `rag_stats` are read-only and marked `parallel_safe`, so the
agent can fan them out alongside other work.

Crucially, scion's system prompt (`scion/agent/prompts.py`) instructs the agent:

> *Use retrieval for documents. When the answer depends on ingested material,
> search the knowledge base (`rag_search`) and cite chunks rather than guessing.*

So once a collection exists, the agent reaches for it on document questions and
grounds its answer in cited passages instead of hallucinating.

---

## Where it's stored

Everything lives in one SQLite database at **`workspace/vectors.db`** (`docs` and
`chunks` tables; embeddings stored as JSON; `numpy` used to speed up vector math
if present, otherwise pure stdlib). The `workspace/` directory is gitignored
runtime state — your ingested corpus stays private to your deployment.

Inspect it any time:

```bash
scion rag stats
# {'documents': 43, 'chunks': 512, 'collections': {'acme': 28, 'globex': 15}}
```

---

## Worked example

```bash
# 1. (once) enable PDF ingest
pip install -e ".[docs]"

# 2. ingest a client's document folder into its own collection
scion rag ingest ./clients/acme --collection acme
# → ingested into 'acme': added=12 updated=0 skipped=0 chunks=204 errors=0

# 3. search it directly from the CLI
scion rag search "what is the refund window?" --collection acme -k 3
#
# [/home/you/clients/acme/refund-policy.pdf#1] (score 0.0328)
# Customers may request a refund within 14 business days of purchase. Refunds
# are issued to the original payment method...
#
# [/home/you/clients/acme/faq.md#4] (score 0.0161)
# Q: How long do refunds take? A: Up to 14 business days...

# 4. let the agent answer, grounded and cited
scion run "Using the acme knowledge base, what's their refund window? Cite it."
# → "ACME's refund window is 14 business days from purchase
#    [refund-policy.pdf#1]."
```

That's the whole loop: ingest a folder, search it, and get an answer pinned to
the exact chunk it came from.
