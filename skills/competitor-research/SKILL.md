---
name: competitor-research
description: Research a competitor and produce a structured brief (use for "research X", "competitor brief", "size up a company").
---

# Competitor Research

A repeatable playbook for turning a company name into a decision-ready brief.
This is an example skill — it shows how a forked agent becomes a *specialist*.

## Steps
1. **Scope.** Note what the operator actually needs (positioning? pricing?
   feature gaps? hiring signals?). If unstated, produce a general brief.
2. **Gather.** Use your native web tools (search + fetch) for the company +
   "pricing", "vs", "review", "funding". If relevant documents were ingested,
   `agent rag search "<query>" --collection <name>` and cite the chunks.
3. **Extract** into these sections:
   - One-line positioning and ICP (ideal customer profile).
   - Pricing & packaging (tiers, anchors, what's gated).
   - Top 3 strengths and top 3 weaknesses (cite sources).
   - Notable recent signals (launches, funding, hiring, churned customers).
   - Where *we* can win (the wedge).
4. **Verify.** Don't state a price or claim you didn't see a source for. Mark
   anything inferred as inferred.
5. **Persist.** Save durable findings with `agent know note "<title>" "<detail>"`
   and, if this is a recurring account, `agent memory remember "<fact>"`.
6. **Deliver** the brief as your reply (`agent tg send <chat_id> "…"` if the task
   came from Telegram) — lead with the wedge.

## Output shape
A tight Markdown brief with the sections above, ≤ 400 words unless asked for more.
