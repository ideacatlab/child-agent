"""Document loaders. Plain text needs nothing; PDF/HTML degrade gracefully."""

from __future__ import annotations

import json
import re
from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".log", ".py", ".js", ".ts", ".csv", ".tsv"}
SUPPORTED = TEXT_SUFFIXES | {".pdf", ".html", ".htm", ".json"}


class LoaderError(Exception):
    pass


def load_document(path: Path | str) -> str:
    """Return the plain-text content of *path*, dispatching on suffix."""
    path = Path(path)
    if not path.exists():
        raise LoaderError(f"no such file: {path}")
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _load_pdf(path)
    if suffix in (".html", ".htm"):
        return _load_html(path)
    if suffix == ".json":
        try:
            return json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2)
        except (json.JSONDecodeError, OSError):
            return path.read_text(encoding="utf-8", errors="replace")
    # default: treat as text
    return path.read_text(encoding="utf-8", errors="replace")


def _load_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # lazy
    except ImportError as exc:  # pragma: no cover
        raise LoaderError(
            "PDF support needs pypdf — install with: pip install 'scion[docs]'"
        ) from exc
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n\n".join(pages)


def _load_html(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        from bs4 import BeautifulSoup  # lazy

        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
    except ImportError:
        # crude fallback: strip tags
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s{2,}", " ", text).strip()


def iter_documents(root: Path | str):
    """Yield every supported file under *root* (or just *root* if it's a file)."""
    root = Path(root)
    if root.is_file():
        if root.suffix.lower() in SUPPORTED:
            yield root
        return
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in SUPPORTED:
            yield p
