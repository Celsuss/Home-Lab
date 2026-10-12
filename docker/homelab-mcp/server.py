#!/usr/bin/env python3
"""homelab-mcp: a small, lean MCP server exposing homelab services as tools.

One process, Streamable HTTP on /mcp, shared by Home Assistant's MCP
integration and Open WebUI's native MCP client.

Every tool schema is sent to the model on every request, and the assistant runs
on a small local model. So the rules are: few tools, short docstrings, flat
string/int arguments, short plain-text results. No tool deletes, updates or
completes anything - read or add only.

A service's tools are registered only when its environment is set, so a missing
token removes those tools instead of leaving broken ones behind.

Environment:
  SEARXNG_URL          e.g. http://searxng.ai-workloads.svc.cluster.local:8080
  FETCH_ENABLED        "1" (default) to register fetch_page
  FETCH_MAX_CHARS      truncate fetched pages (default 4000)
  DONETICK_URL         e.g. http://donetick.utils.svc.cluster.local:2021
  DONETICK_TOKEN       Donetick access token (Settings -> Access tokens)
  TANDOOR_URL          e.g. http://tandoor-recipes.tandoor.svc.cluster.local
  TANDOOR_TOKEN        Tandoor API token (read scope is enough)
  TANDOOR_PUBLIC_URL   base for recipe links, e.g. https://tandoor.homelab.local
  PROTON_ICS_URL       Proton Calendar "Full view" share link. It contains the
                       calendar's decryption key: Vault only, never logged
  CALENDAR_TZ          timezone events are shown in (default UTC)
  CALENDAR_CACHE_SECONDS  how long a fetched calendar is reused (default 900)
  HOST / PORT          bind address (default 0.0.0.0:8000)
"""

import asyncio
import datetime
import functools
import ipaddress
import logging
import os
import socket
import time
import urllib.parse
import zoneinfo

import httpx
import icalendar
import recurring_ical_events
import trafilatura
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

log = logging.getLogger("homelab-mcp")

TIMEOUT = httpx.Timeout(15.0)
# An honest bot UA: Wikipedia and others 403 a fake-browser string with extras.
USER_AGENT = "homelab-mcp/0.1 (+https://github.com/Celsuss/Home-Lab)"

mcp = MCPServer(
    name="homelab",
    instructions="Tools for the user's homelab: web search, reading web pages, chores, recipes and calendar.",
)


@mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "tools": [t.name for t in await mcp.list_tools()]})


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def tool(fn):
    """Register fn as a tool whose HTTP failures come back as a readable line.

    Without this the model only sees "Error executing tool …" and guesses.
    structured_output=False drops the outputSchema/structuredContent copy that
    would otherwise double every result in the model's context.

    The schema's pydantic `title` keys ("Query", "web_searchArguments") are
    dropped: clients may pass them to the model, and they are ~20% of
    tools/list. The schema is only listed, never used for validation, so
    editing it is safe. _tool_manager is private: re-check on an mcp upgrade.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except httpx.HTTPStatusError as exc:
            return f"{fn.__name__} failed: HTTP {exc.response.status_code} from {exc.request.url.host}."
        except httpx.HTTPError as exc:
            return f"{fn.__name__} failed: {exc.request.url.host} is unreachable ({type(exc).__name__})."

    registered = mcp.tool(structured_output=False)(wrapper)
    info = mcp._tool_manager.get_tool(fn.__name__)
    info.parameters = strip_titles(info.parameters)
    return registered


def strip_titles(schema):
    if isinstance(schema, dict):
        if "properties" in schema:  # property names are arguments, even one called "title"
            schema = {**schema, "properties": {k: strip_titles(v) for k, v in schema["properties"].items()}}
        return {k: (v if k == "properties" else strip_titles(v)) for k, v in schema.items() if k != "title"}
    if isinstance(schema, list):
        return [strip_titles(v) for v in schema]
    return schema


def clip(text: str, limit: int) -> str:
    text = " ".join(text.split()) if "\n" not in text else text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --- Web search (SearXNG) ----------------------------------------------------

SEARXNG_URL = env("SEARXNG_URL").rstrip("/")

if SEARXNG_URL:

    @tool
    async def web_search(query: str) -> str:
        """Search the web. Use for current events, facts you are unsure of, or anything outside the home."""
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{SEARXNG_URL}/search", params={"q": query, "format": "json"}
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])[:5]
        if not results:
            return f"No results for {query!r}."
        return "\n".join(
            f"{i}. {r.get('title', '').strip()} - {r.get('url', '')}\n   {clip(r.get('content') or '', 240)}"
            for i, r in enumerate(results, 1)
        )


# --- Fetch a web page ---------------------------------------------------------

FETCH_ENABLED = env("FETCH_ENABLED", "1") == "1"
FETCH_MAX_CHARS = int(env("FETCH_MAX_CHARS", "4000"))


async def assert_public(url: str) -> None:
    """Refuse anything that is not plain http(s) to a public address.

    The NetworkPolicy already blocks private ranges; this is the second layer,
    and gives the model a readable error instead of a connection reset.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("only http(s) URLs are allowed")
    infos = await asyncio.get_running_loop().getaddrinfo(
        parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM
    )
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError(f"{parts.hostname} is not a public address")


if FETCH_ENABLED:

    @tool
    async def fetch_page(url: str) -> str:
        """Read the main text of a public web page: any URL the user gives, or a search result."""
        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=False
        ) as client:
            # Follow redirects by hand so every hop gets the public-address check.
            for _ in range(5):
                try:
                    await assert_public(url)
                    resp = await client.get(url)
                except (ValueError, OSError, httpx.HTTPError) as exc:
                    return f"Could not fetch the page: {exc or type(exc).__name__}."
                if resp.is_redirect:
                    url = urllib.parse.urljoin(url, resp.headers["location"])
                    continue
                break
            else:
                return "Too many redirects."
        if resp.status_code >= 400:
            return f"Could not fetch the page: HTTP {resp.status_code}."
        text = trafilatura.extract(resp.text, url=url, include_comments=False) or ""
        if not text:
            return "The page has no readable text."
        return clip(text, FETCH_MAX_CHARS)


# --- Donetick (chores) --------------------------------------------------------

DONETICK_URL = env("DONETICK_URL").rstrip("/")
DONETICK_TOKEN = env("DONETICK_TOKEN")


def donetick() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{DONETICK_URL}/eapi/v1", timeout=TIMEOUT, headers={"secretkey": DONETICK_TOKEN}
    )


if DONETICK_URL and DONETICK_TOKEN:

    @tool
    async def add_chore(name: str, due_date: str = "") -> str:
        """Add a chore or to-do to the user's chore list. due_date is optional, as YYYY-MM-DD."""
        body = {"name": name}
        if due_date:
            body["dueDate"] = due_date
        async with donetick() as client:
            resp = await client.post("/chore", json=body)
        if resp.status_code >= 400:
            return f"Donetick refused the chore: {resp.text[:200]}"
        due = f", due {due_date}" if due_date else ""
        return f"Added chore {name!r}{due}."

    @tool
    async def list_chores() -> str:
        """List the user's open chores, soonest due first."""
        async with donetick() as client:
            resp = await client.get("/chore")
            resp.raise_for_status()
            chores = [c for c in resp.json() if c.get("isActive", True)]
        if not chores:
            return "No open chores."
        today = datetime.date.today().isoformat()
        chores.sort(key=lambda c: c.get("nextDueDate") or "9999")
        lines = []
        for c in chores[:15]:
            due = (c.get("nextDueDate") or "")[:10]
            flag = " (overdue)" if due and due < today else ""
            lines.append(f"- {c.get('name')}" + (f", due {due}{flag}" if due else ""))
        more = f"\n…and {len(chores) - 15} more." if len(chores) > 15 else ""
        return "\n".join(lines) + more


# --- Tandoor (recipes) --------------------------------------------------------

TANDOOR_URL = env("TANDOOR_URL").rstrip("/")
TANDOOR_TOKEN = env("TANDOOR_TOKEN")
TANDOOR_PUBLIC_URL = env("TANDOOR_PUBLIC_URL", TANDOOR_URL).rstrip("/")


def tandoor() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{TANDOOR_URL}/api",
        timeout=TIMEOUT,
        headers={"Authorization": f"Bearer {TANDOOR_TOKEN}"},
    )


def fmt_amount(amount) -> str:
    if not amount:
        return ""
    return f"{amount:g} " if isinstance(amount, (int, float)) else f"{amount} "


if TANDOOR_URL and TANDOOR_TOKEN:

    @tool
    async def search_recipes(query: str = "") -> str:
        """Search the user's recipes by name, ingredient or keyword. Leave query empty to list all recipes."""
        # Models tend to search for the literal word "all" when asked to list
        # everything; Tandoor would fuzzy-match that against recipe text.
        if query.strip().lower() in ("all", "*", "everything", "any"):
            query = ""
        page_size = 8 if query else 30
        async with tandoor() as client:
            resp = await client.get("/recipe/", params={"query": query, "page_size": page_size})
            resp.raise_for_status()
            data = resp.json()
        recipes, total = data.get("results", []), data.get("count", 0)
        if not recipes:
            return f"No recipes match {query!r}." if query else "The recipe collection is empty."
        what = f"{total} recipes match {query!r}" if query else f"{total} recipes in total"
        shown = f", showing {len(recipes)}" if total > len(recipes) else ""
        return f"{what}{shown}:\n" + "\n".join(
            f"- {r['name']} (id {r['id']})" + (f": {clip(' '.join(r['description'].split()), 100)}" if query and r.get("description") else "")
            for r in recipes
        )

    @tool
    async def get_recipe(recipe_id: int) -> str:
        """Get the ingredients and steps of one recipe, by the id from search_recipes."""
        async with tandoor() as client:
            resp = await client.get(f"/recipe/{recipe_id}/")
            if resp.status_code == 404:
                return f"No recipe with id {recipe_id}."
            resp.raise_for_status()
            r = resp.json()
        ingredients, steps = [], []
        for n, step in enumerate(r.get("steps", []), 1):
            for ing in step.get("ingredients", []):
                if ing.get("is_header"):
                    continue
                # An ingredient line that was never linked to a food (e.g. an
                # import Tandoor could not parse) only has its original text.
                food = (ing.get("food") or {}).get("name", "")
                if not food:
                    if ing.get("original_text"):
                        ingredients.append(f"- {ing['original_text'].strip()}")
                        continue
                    if not ing.get("note"):
                        continue
                unit = (ing.get("unit") or {}).get("name", "")
                note = f" ({ing['note']})" if ing.get("note") else ""
                ingredients.append(f"- {fmt_amount(ing.get('amount'))}{unit + ' ' if unit else ''}{food}{note}".rstrip())
            if step.get("instruction"):
                steps.append(f"{n}. {clip(step['instruction'], 400)}")
        parts = [f"{r['name']} - serves {r.get('servings', '?')}, {TANDOOR_PUBLIC_URL}/view/recipe/{recipe_id}"]
        if ingredients:
            parts += ["Ingredients:", *ingredients]
        if steps:
            parts += ["Steps:", *steps]
        return clip("\n".join(parts), 4000)


# --- Calendar (Proton share link, read-only) ----------------------------------

PROTON_ICS_URL = env("PROTON_ICS_URL")
# httpx logs every request URL at INFO, and this URL is a decryption key. Set
# at import, not in main(): the MCP library configures logging on its own.
logging.getLogger("httpx").setLevel(logging.WARNING)
CALENDAR_TZ = zoneinfo.ZoneInfo(env("CALENDAR_TZ", "UTC"))
CALENDAR_CACHE_SECONDS = int(env("CALENDAR_CACHE_SECONDS", "900"))
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_calendar_cache: tuple[float, icalendar.Calendar] | None = None
_calendar_lock = asyncio.Lock()


async def proton_calendar() -> icalendar.Calendar:
    """The parsed calendar, refetched at most every CALENDAR_CACHE_SECONDS.

    Proton itself only refreshes the shared feed every few hours, so polling
    faster gains nothing. A failed refresh falls back to the last good copy.
    """
    global _calendar_cache
    async with _calendar_lock:
        if _calendar_cache and time.monotonic() - _calendar_cache[0] < CALENDAR_CACHE_SECONDS:
            return _calendar_cache[1]
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
            ) as client:
                resp = await client.get(PROTON_ICS_URL)
                resp.raise_for_status()
            cal = icalendar.Calendar.from_ical(resp.content)
        except (httpx.HTTPError, ValueError):
            if _calendar_cache:
                log.warning("calendar refresh failed, serving the cached copy")
                return _calendar_cache[1]
            raise
        _calendar_cache = (time.monotonic(), cal)
        return cal


def parse_day(text: str, today: datetime.date) -> datetime.date:
    """YYYY-MM-DD, 'today', 'tomorrow' or a weekday name (the next one, today included).

    Small models also send "this friday" / "on friday" / "next friday", so
    those prefixes are accepted; "next" skips today.
    """
    words = text.strip().lower().split()
    skip_today = bool(words) and words[0] == "next"
    if words and words[0] in ("this", "on", "next", "coming"):
        words = words[1:]
    text = " ".join(words)
    if text in ("", "today"):
        return today
    if text == "tomorrow":
        return today + datetime.timedelta(days=1)
    if text == "yesterday":
        return today - datetime.timedelta(days=1)
    if text == "week":  # "this week" starts today, "next week" on next Monday
        return today + datetime.timedelta(days=(7 - today.weekday()) if skip_today else 0)
    if text.rstrip("s") in WEEKDAYS:
        ahead = (WEEKDAYS.index(text.rstrip("s")) - today.weekday()) % 7
        return today + datetime.timedelta(days=ahead or (7 if skip_today else 0))
    return datetime.date.fromisoformat(text)


def as_local(value) -> datetime.datetime:
    """An event time as an aware local datetime; dates become local midnight."""
    if not isinstance(value, datetime.datetime):
        return datetime.datetime.combine(value, datetime.time.min, CALENDAR_TZ)
    # Floating times (no TZID) are the calendar owner's wall clock.
    return value.astimezone(CALENDAR_TZ) if value.tzinfo else value.replace(tzinfo=CALENDAR_TZ)


def fmt_day(day: datetime.date) -> str:
    return day.strftime("%a %d %b")


if PROTON_ICS_URL:

    @tool
    async def calendar_agenda(start_date: str = "", days: int = 1) -> str:
        """List the user's calendar events from start_date (default today; YYYY-MM-DD, 'tomorrow' or a weekday) for days days (7 for a week)."""
        today = datetime.datetime.now(CALENDAR_TZ).date()
        try:
            first = parse_day(start_date, today)
        except ValueError:
            return f"Could not read the date {start_date!r}; use YYYY-MM-DD, 'today', 'tomorrow' or a weekday."
        days = max(1, min(int(days), 31))
        last = first + datetime.timedelta(days=days - 1)
        window_start = as_local(first)
        window_end = as_local(last + datetime.timedelta(days=1))
        try:
            cal = await proton_calendar()
            found = recurring_ical_events.of(cal).between(window_start, window_end)
        except ValueError as exc:
            return f"calendar_agenda failed: the calendar could not be parsed ({exc})."

        events = []
        for ev in found:
            if str(ev.get("STATUS", "")).upper() == "CANCELLED":
                continue
            dtstart = ev.decoded("DTSTART")
            all_day = not isinstance(dtstart, datetime.datetime)
            start = as_local(dtstart)
            if "DTEND" in ev:
                end = as_local(ev.decoded("DTEND"))
            elif "DURATION" in ev:
                end = start + ev.decoded("DURATION")
            else:
                end = start + (datetime.timedelta(days=1) if all_day else datetime.timedelta(0))
            events.append((start, end, all_day, ev))
        events.sort(key=lambda e: (e[0], not e[2]))

        span = fmt_day(first) if days == 1 else f"{fmt_day(first)} to {fmt_day(last)}"
        header = f"Calendar for {span} (today is {fmt_day(today)}, times {CALENDAR_TZ.key})"
        if not events:
            return f"{header}: no events."

        lines, current_day = [header + ":"], None
        for start, end, all_day, ev in events[:40]:
            # Events that began before the window (a trip, a late meeting)
            # are listed under the first day they overlap.
            day = max(start.date(), first)
            if day != current_day:
                lines.append(fmt_day(day))
                current_day = day
            last_day = (end - datetime.timedelta(microseconds=1)).date() if end > start else start.date()
            if all_day:
                when = "all day" if last_day <= start.date() else f"all day, {fmt_day(start.date())} to {fmt_day(last_day)}"
            else:
                when = start.strftime("%H:%M")
                if end > start:
                    when += "-" + (end.strftime("%H:%M") if last_day == start.date() else f"{fmt_day(last_day)} {end.strftime('%H:%M')}")
                if start.date() < day:
                    when = f"since {fmt_day(start.date())} {when}"
            title = clip(str(ev.get("SUMMARY", "")).strip() or "(no title)", 100)
            location = clip(str(ev.get("LOCATION", "")).strip(), 60)
            lines.append(f"- {when} {title}" + (f" @ {location}" if location else ""))
        if len(events) > 40:
            lines.append(f"…and {len(events) - 40} more.")
        return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    tools = [t.name for t in asyncio.run(mcp.list_tools())]
    log.info("registered tools: %s", ", ".join(tools) or "(none)")
    # Stateless + JSON responses: no server-side sessions to lose when the pod
    # restarts, so HA and Open WebUI never hold a dead session id.
    mcp.run(
        transport="streamable-http",
        host=env("HOST", "0.0.0.0"),
        port=int(env("PORT", "8000")),
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
