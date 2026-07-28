# web_search.py

from core.clock import local_now
from core.providers import GroundedSearchProvider, ProviderError


def _provider_search(
    query: str,
    provider: GroundedSearchProvider | None,
) -> str:
    if provider is None:
        raise ProviderError("No grounded search provider is configured.")
    return provider.search(query)


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title":   r.get("title",  ""),
                "snippet": r.get("body",   ""),
                "url":     r.get("href",   ""),
            })
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """DDG news search — returns actual articles, not website homepages."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, timelimit="d", max_results=max_results):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("url",    ""),
                    "source":  r.get("source", ""),
                    "date":    r.get("date",   ""),
                })
    except Exception as e:
        print(f"[WebSearch] DDG news failed ({e}); falling back to text search")
        results = _ddg_search(query, max_results=max_results)
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   Source: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return f"No news found for: {query}"

    lines = [f"Latest news: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        if not title:
            continue
        src = f"  [{r['source']}]" if r.get("source") else ""
        published = f" — {r['date']}" if r.get("date") else ""
        lines.append(f"{i}. {title}{src}{published}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:140]}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


# ── Briefing helper ────────────────────────────────────────────────────────────

def _provider_headlines(
    provider: GroundedSearchProvider,
    n: int = 5,
) -> tuple[list[str], str]:
    """
    Fetches current headlines via Gemini grounded search.
    Optimised for speed: minimal prompt + strict token cap.
    Returns (headline_list, raw_text_for_display).
    """
    import re

    raw = provider.search(
        f"Current world news: {n} headlines. Numbered list, titles only."
    )

    headlines = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Only accept lines that begin with a number — skips preamble/closing sentences
        if not re.match(r'^[\d]+[.\)\-]', line):
            continue
        clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
        clean = re.sub(r'^\*+\s*',          '', clean).strip()
        if clean and len(clean) > 10:
            headlines.append(clean)

    return headlines[:n], raw.strip()


# ── Modes ──────────────────────────────────────────────────────────────────────

def _search(query: str, provider: GroundedSearchProvider | None) -> str:
    """Default search — Gemini grounded, DDG fallback."""
    try:
        return _provider_search(query, provider)
    except Exception as e:
        print(f"[WebSearch] Grounded provider failed ({e}); trying DDG")
        results = _ddg_search(query)
        return _format_ddg(query, results)


def _news(query: str, provider: GroundedSearchProvider | None) -> str:
    """
    Runs Gemini grounded search AND DDG news in parallel.
    Returns whichever delivers a valid result first; cancels the other.
    """
    import threading

    today = local_now().strftime("%Y-%m-%d")
    topic = query or "top world news"
    gemini_query = (
        f"Verified breaking news for {today} in America/Buenos_Aires about: {topic}. "
        "Return only events first reported or materially updated within the last 24 hours. "
        "Include each article's publication date and omit undated or older stories."
    )
    ddg_query = topic

    result_box  = [None]   # first valid result lands here
    lock        = threading.Lock()
    done_evt    = threading.Event()
    failures    = [0]

    def _store(r: str) -> None:
        if r and len(r) > 60:
            with lock:
                if result_box[0] is None:
                    result_box[0] = r
            done_evt.set()
        else:
            with lock:
                failures[0] += 1
                if failures[0] >= 2:   # both failed — unblock caller
                    done_evt.set()

    def _try_gemini():
        try:
            _store(_provider_search(gemini_query, provider))
        except Exception as e:
            print(f"[WebSearch] Grounded news provider failed ({e})")
            _store("")

    def _try_ddg():
        try:
            results = _ddg_news(ddg_query, max_results=8)
            _store(_format_news(ddg_query, results))
        except Exception as e:
            print(f"[WebSearch] DDG news failed ({e})")
            _store("")

    threading.Thread(target=_try_gemini, daemon=True).start()
    threading.Thread(target=_try_ddg,    daemon=True).start()

    done_evt.wait(timeout=10.0)
    return result_box[0] or f"No news found for: {query}"


def _research(query: str, provider: GroundedSearchProvider | None) -> str:
    """
    Deep dive — asks Gemini for a comprehensive answer with context.
    Falls back to a wider DDG fetch.
    """
    research_query = (
        f"Comprehensive, detailed explanation of: {query}. "
        "Include background context, key facts, current state, and important nuances."
    )
    try:
        return _provider_search(research_query, provider)
    except Exception as e:
        print(f"[WebSearch] Grounded research failed ({e}); using DDG")
        results = _ddg_search(query, max_results=10)
        return _format_ddg(query, results)


def _price(query: str, provider: GroundedSearchProvider | None) -> str:
    """Product price lookup — searches for current market prices."""
    price_query = f"current price of {query} — how much does it cost today"
    try:
        return _provider_search(price_query, provider)
    except Exception as e:
        print(f"[WebSearch] Grounded price lookup failed ({e}); using DDG")
        results = _ddg_search(f"{query} price buy", max_results=6)
        return _format_ddg(query, results)


def _compare(
    items: list[str],
    aspect: str,
    provider: GroundedSearchProvider | None,
) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _provider_search(query, provider)
    except Exception as e:
        print(f"[WebSearch] Grounded comparison failed ({e}); using DDG")

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    return "\n".join(lines)


# ── Public entry point ─────────────────────────────────────────────────────────

def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
    provider: GroundedSearchProvider | None = None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"

    if player:
        player.write_log(f"[Search:{mode}] {query or ', '.join(items)}")

    print(f"[WebSearch] mode={mode!r} query={query!r}")

    try:
        if mode == "compare" and items:
            return _compare(items, aspect, provider)
        if mode == "news":
            return _news(query, provider)
        if mode == "research":
            return _research(query, provider)
        if mode == "price":
            return _price(query, provider)
        return _search(query, provider)

    except Exception as e:
        print(f"[WebSearch] All backends failed: {e}")
        return f"Search failed: {e}"
