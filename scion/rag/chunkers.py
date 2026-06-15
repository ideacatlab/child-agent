"""Text chunking. Structure-aware where cheap, with overlap to preserve context."""

from __future__ import annotations

import re

_HEADER = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)


def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, *, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    """Split *text* into ~``chunk_size``-char chunks on paragraph boundaries,
    carrying ``overlap`` chars of tail context between consecutive chunks.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    paras = _split_paragraphs(text)
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if len(para) > chunk_size:
            # hard-split an oversized paragraph
            if buf:
                chunks.append(buf.strip())
                buf = ""
            for i in range(0, len(para), chunk_size - overlap):
                chunks.append(para[i : i + chunk_size].strip())
            continue
        if len(buf) + len(para) + 2 > chunk_size and buf:
            chunks.append(buf.strip())
            tail = buf[-overlap:] if overlap else ""
            buf = (tail + "\n\n" + para).strip()
        else:
            buf = (buf + "\n\n" + para).strip() if buf else para
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c]


def chunk_markdown(text: str, *, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    """Markdown-aware: break on headers first, then size each section."""
    text = (text or "").strip()
    if not text:
        return []
    positions = [m.start() for m in _HEADER.finditer(text)]
    if not positions:
        return chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    sections: list[str] = []
    bounds = positions + [len(text)]
    if positions[0] > 0:
        sections.append(text[: positions[0]])
    for i in range(len(positions)):
        sections.append(text[bounds[i] : bounds[i + 1]])
    out: list[str] = []
    for sec in sections:
        out.extend(chunk_text(sec, chunk_size=chunk_size, overlap=overlap))
    return out
