"""Web access: fetch a URL, and a best-effort keyless web search."""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request

from scion.security.policy import SAFE
from scion.tools.base import ToolError, tool

_UA = "Mozilla/5.0 (compatible; scion-agent/0.1; +https://example.com/scion)"
_MAX = 20000


def _get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _strip_html(raw: str) -> str:
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s{2,}", " ", text).strip()


@tool(risk=SAFE, parallel_safe=True)
def web_fetch(url: str) -> str:
    """Fetch a URL and return its readable text content.

    Args:
        url: the http(s) URL to fetch.
    """
    if not url.startswith(("http://", "https://")):
        raise ToolError("url must start with http:// or https://")
    try:
        raw = _get(url)
    except Exception as exc:
        raise ToolError(f"fetch failed: {exc}")
    text = _strip_html(raw) if "<" in raw[:512] else raw
    return text[:_MAX] + ("\n…[truncated]" if len(text) > _MAX else "")


@tool(risk=SAFE, parallel_safe=True)
def web_search(query: str, max_results: int = 6) -> str:
    """Search the web (keyless, via DuckDuckGo's HTML endpoint).

    Returns a list of title / url / snippet. For higher quality, wire up a real
    search API in a custom tool.

    Args:
        query: the search query.
        max_results: how many results to return.
    """
    url = "https://duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    try:
        raw = _get(url)
    except Exception as exc:
        raise ToolError(f"search failed: {exc}")
    results: list[str] = []
    pattern = re.compile(
        r'result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'result__snippet[^>]*>(?P<snip>.*?)</a>',
        re.S,
    )
    for m in pattern.finditer(raw):
        link = html.unescape(m.group("url"))
        # DDG wraps targets in a redirect; pull out uddg=
        if "uddg=" in link:
            link = urllib.parse.unquote(re.search(r"uddg=([^&]+)", link).group(1))
        title = _strip_html(m.group("title"))
        snip = _strip_html(m.group("snip"))
        results.append(f"• {title}\n  {link}\n  {snip[:200]}")
        if len(results) >= max_results:
            break
    return "\n\n".join(results) or "(no results; the search endpoint may have changed)"
