#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Tool-choice regression check for homelab-mcp + Home Assistant's agent.

Fetches the live tools/list, adds HA's own Assist tools, and sends each case in
cases.yaml to Ollama /api/chat the way HA does (its system prompt, model,
think off, streaming), N times. Prints the tool picked per run and a pass rate
per case, plus the tools/list size against the schema budget.

Tools are never executed, so a run has no side effects.

  uv run docker/homelab-mcp/eval/tool_choice.py \
      --mcp-url http://<homelab-mcp-clusterip>:8000/mcp \
      --ollama-url http://<ollama-clusterip>:11434

Exit code 1 if tools/list (compact, titles stripped) is over --budget bytes.
"""

import argparse
import collections
import json
import pathlib
import re
import sys
import time
import urllib.request

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
PREFIX = "homelab__"  # HA's MCP integration namespaces the tools with this
HA_PREFIX = "assist__"  # and, with two LLM APIs selected, HA's own tools too
# gemma4's native call syntax leaking into the reply (`name{arg:<|"|>x<|"|>}`).
TEXT_CALL = re.compile(r'<\|"\|>|<\|?tool_call|\b\w+\{\w+:')
TEXT_WITH_CALL = " +text"  # a call that also carries reply text (see chat())


def post(url: str, body: dict, headers: dict | None = None, timeout: float = 120):
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})}
    )
    return urllib.request.urlopen(req, timeout=timeout)


def mcp_tools(mcp_url: str) -> list[dict]:
    # homelab-mcp runs stateless with JSON responses, so tools/list needs no
    # initialize handshake.
    with post(
        mcp_url,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"Accept": "application/json, text/event-stream"},
        timeout=15,
    ) as resp:
        return json.load(resp)["result"]["tools"]


def strip_titles(schema):
    """Drop pydantic's `title` keys, which HA doesn't pass on to the model."""
    if isinstance(schema, dict):
        return {k: strip_titles(v) for k, v in schema.items() if k != "title"}
    if isinstance(schema, list):
        return [strip_titles(v) for v in schema]
    return schema


def as_ollama(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


def ha_prompt(path: pathlib.Path) -> str:
    """The prompt is the first fenced block in docs/home-assistant/system-prompt.md."""
    match = re.search(r"^```\n(.*?)^```", path.read_text(), re.S | re.M)
    if not match:
        sys.exit(f"no fenced prompt block in {path}")
    return match.group(1).strip()


def system_message(prompt: str, ha: dict) -> str:
    # HA 2026.10: the user's instructions, then the merged API prompt (static
    # context included), as the Assist debug view shows it.
    return f"{prompt}\n{ha['api_prompt']}\n\n"


def chat(ollama_url: str, body: dict) -> tuple[str, str, list[str]]:
    """One request. Returns (outcome, detail, called): outcome is the first tool's name,
    "text tool call" or "no call"; called is every tool called in the turn."""
    content, calls = "", []
    with post(f"{ollama_url}/api/chat", body) as resp:
        for line in resp:
            msg = json.loads(line).get("message", {})
            content += msg.get("content", "")
            calls += msg.get("tool_calls") or []
    if calls:
        fn = calls[0]["function"]
        # A reply written next to the call is taken as the answer: HA's second
        # pass after the tool result then comes back empty and Assist shows
        # "Unable to get response". Seen live with remember (2026-10-13).
        suffix = TEXT_WITH_CALL if content.strip() else ""
        detail = " ; ".join(
            f"{c['function']['name']} {json.dumps(c['function'].get('arguments', {}), ensure_ascii=False)}"
            for c in calls
        )
        return fn["name"] + suffix, detail, [c["function"]["name"] for c in calls]
    snippet = " ".join(content.split())[:80]
    return ("text tool call" if TEXT_CALL.search(content) else "no call"), snippet, []


def short(outcome: str) -> str:
    return outcome.removeprefix(PREFIX).removeprefix(HA_PREFIX)


def passed(case: dict, outcome: str, called: list[str]) -> bool:
    if outcome == "text tool call" or outcome.endswith(TEXT_WITH_CALL):
        return False
    # HA runs every call in the turn, so a forbidden one anywhere has its side
    # effect even when the first call is right (live 2026-10-19: add "none",
    # then read the list).
    if any(short(name) in case.get("forbid", []) for name in called):
        return False
    if case.get("avoid") == "homelab":
        return not outcome.startswith(PREFIX)
    expect = case["expect"]
    if outcome == "no call":
        return "none" in expect
    return short(outcome) in expect


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mcp-url", required=True, help="homelab-mcp /mcp endpoint")
    ap.add_argument("--ollama-url", required=True, help="Ollama base URL")
    ap.add_argument("--model", default="gemma4:12b-it-qat", help="the HA voice model (default gemma4:12b-it-qat)")
    ap.add_argument("-n", type=int, default=8, help="runs per case (default 8)")
    ap.add_argument("--num-ctx", type=int, default=32768, help="matches the live n_ctx")
    ap.add_argument("--cases", type=pathlib.Path, default=HERE / "cases.yaml")
    ap.add_argument("--prompt", type=pathlib.Path, default=REPO / "docs/home-assistant/system-prompt.md")
    ap.add_argument("--only", help="run only cases whose utterance contains this text")
    ap.add_argument("--budget", type=int, default=2200, help="tools/list byte budget (default 2200)")
    ap.add_argument("-v", "--verbose", action="store_true", help="print every run's arguments or reply")
    args = ap.parse_args()

    spec = yaml.safe_load(args.cases.read_text())
    ha = spec["ha"]
    cases = [c for c in spec["cases"] if not args.only or args.only.lower() in c["utterance"].lower()]

    remote = mcp_tools(args.mcp_url)
    # The budget counts what reaches the model: compact JSON without the
    # pydantic titles (about a fifth of the raw response).
    raw = len(json.dumps(remote, separators=(",", ":")))
    size = len(json.dumps(strip_titles(remote), separators=(",", ":")))
    over = size > args.budget
    print(
        f"tools/list: {len(remote)} tools, {size} B to the model (budget {args.budget} B), "
        f"{raw} B raw{'  OVER BUDGET' if over else ''}"
    )
    print("  " + ", ".join(t["name"] for t in remote))

    tools = [as_ollama(HA_PREFIX + t["name"], t["description"], t["parameters"]) for t in ha["tools"]]
    tools += [as_ollama(PREFIX + t["name"], t.get("description", ""), strip_titles(t["inputSchema"])) for t in remote]
    body = {
        "model": args.model,
        "stream": True,
        "think": False,
        "options": {"num_ctx": args.num_ctx},
        "messages": [{"role": "system", "content": system_message(ha_prompt(args.prompt), ha)}, None],
        "tools": tools,
    }
    print(f"model {args.model}, {len(tools)} tools sent, {len(cases)} cases x {args.n} runs\n")

    total = total_ok = 0
    failing = []
    for case in cases:
        body["messages"][1] = {"role": "user", "content": case["utterance"]}
        outcomes, ok, started = collections.Counter(), 0, time.monotonic()
        for _ in range(args.n):
            outcome, detail, called = chat(args.ollama_url, body)
            outcomes[short(outcome) + (" (+more)" if len(called) > 1 else "")] += 1
            hit = passed(case, outcome, called)
            ok += hit
            if args.verbose:
                print(f"    {'ok ' if hit else 'BAD'} {outcome}: {detail}")
        total, total_ok = total + args.n, total_ok + ok
        want = "not homelab" if case.get("avoid") == "homelab" else "|".join(case["expect"])
        seen = ", ".join(f"{name} {count}" for name, count in outcomes.most_common())
        avg = (time.monotonic() - started) / args.n
        mark = "  " if ok == args.n else "!!"
        print(f"{mark} {ok}/{args.n}  {case['utterance'][:52]:52}  want {want:26} got {seen}  ({avg:.1f}s)")
        if ok < args.n:
            failing.append(case["utterance"])

    print(f"\nTotal {total_ok}/{total} ({100 * total_ok / max(total, 1):.0f}%), {len(failing)} of {len(cases)} cases below {args.n}/{args.n}.")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
