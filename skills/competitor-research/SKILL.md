---
name: competitor-research
description: Research a competitor and produce a structured brief (use for "research X", "competitor brief", "size up a company").
---

# Competitor Research

A repeatable playbook for turning a company name into a decision-ready brief.
This is an example skill — it shows how a forked scion becomes a *specialist*.

## Steps
1. **Scope.** Note what the operator actually needs (positioning? pricing?
   feature gaps? hiring signals?). If unstated, produce a general brief.
2. **Gather.** Use `web_search` for the company + "pricing", "vs", "review",
   "funding". Use `web_fetch` on the most useful 3–5 pages (their site, a
   comparison, a review roundup). If documents were ingested, `rag_search` them.
3. **Extract** into these sections:
   - One-line positioning and ICP (ideal customer profile).
   - Pricing & packaging (tiers, anchors, what's gated).
   - Top 3 strengths and top 3 weaknesses (cite sources).
   - Notable recent signals (launches, funding, hiring, churned customers).
   - Where *we* can win (the wedge).
4. **Verify.** Don't state a price or claim you didn't see a source for. Mark
   anything inferred as inferred.
5. **Persist.** Save durable findings with `note_knowledge` and, if this is
   recurring, keep the company in core memory (`core_memory_append open_loops`).
6. **Deliver** the brief as the final message — lead with the wedge.

## Output shape
A tight Markdown brief with the sections above, ≤ 400 words unless asked for more.
