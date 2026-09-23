
# Open web UI

## Post deployment
Manual steps required before deploy:
1. Create Vault secret: `vault kv put secret/homelab/open-webui webui-secret-key=<generated-key>`
2. After deploy: nothing to register. 0.11.4 ships native `search_web`,
   `fetch_url`, knowledge, memory, task and calendar tools, so no external tool
   server is needed. The `mcpo` chart is scaled to zero — see
   `helm/charts/mcpo/README.md` before re-enabling it.

   **Remove any leftover `mcpo` entries** (see [Web search](#web-search) below).
   Tool server and MCP server connections are PersistentConfig stored in the
   database, so `TOOL_SERVER_CONNECTIONS` will NOT override an existing value —
   they have to be deleted in the UI.

## Web search

Provided by the standalone `searxng` chart in this namespace, via
`ENABLE_WEB_SEARCH` + `SEARXNG_QUERY_URL` in `values.yaml`. Open WebUI's native
`search_web` tool uses it.

### Zero search results (2026-09-23)

Symptom: the model calls `search_web`, gets `[]` back, and reports it could not
find anything. Web search looks correctly configured, because it *is* — the
request reaches SearXNG fine and SearXNG answers `HTTP 200` with an empty result
list.

Cause: all four general web engines SearXNG enables by default were blocking
this egress IP.

```console
$ curl 'http://searxng.ai-workloads.svc.cluster.local:8080/search?q=test&format=json'     | jq '{n: (.results|length), unresponsive: .unresponsive_engines}'
{
  "n": 0,
  "unresponsive": [["brave","too many requests"], ["duckduckgo","CAPTCHA"],
                   ["google","access denied"], ["startpage","CAPTCHA"]]
}
```

Fixed by enabling `bing`, `yandex` and `seznam` in `helm/charts/searxng` — see
the comments in that chart's `values.yaml`. **Diagnose this at SearXNG, not in
Open WebUI:** `unresponsive_engines` in the JSON response names the real
problem, and `just smoke-search` checks it in one command.

### Two other things that looked like the same bug

- **"Failed to connect to MCP server 'Web fetch'" / `Connection failed` on
  Verify connection.** Unrelated to web search: `mcpo` was serving zero tools,
  and was registered under 0.11's MCP servers section even though it is an
  MCP → *OpenAPI* proxy. Details in `helm/charts/mcpo/README.md`.
- **`KeyError: 'model'` in `run_initial_title_generation`.** Upstream 0.11.4
  bug; breaks auto-titling of new chats only, not responses.

## Upgrade notes

### 0.9.6 → 0.11.4 (2026-09-23)

Eight releases in one hop. 0.10.0, 0.11.0 and 0.11.1 each ship **one-way** SQLite
schema migrations — upstream does not support downgrading afterwards. Always
snapshot the PVC before bumping the tag:

```bash
# this node is the machine itself; local-path PV lives on disk
kubectl -n ai-workloads scale deploy/open-webui --replicas=0
sudo tar -C /var/lib/rancher/k3s/storage \
  -czf ~/open-webui-pvc-$(date +%F).tar.gz \
  pvc-<uid>_ai-workloads_open-webui-pvc
```

Rollback is *restore the tarball then revert the commit* — reverting alone leaves
0.9.6 pointed at a 0.11.x schema.

Behaviour changes that need a decision in the UI after upgrading:

- **Native tool calling became the default** in 0.10.0. Models that never explicitly
  picked a mode flip from the old behaviour (now named "Legacy") to Native. Local
  Ollama models often handle native tool calls poorly — if the mcpo tools below stop
  working, switch the model back to Legacy (per chat, per model, or in the default
  model parameters).
- **Admin settings moved** into the settings window under an Admin section (0.11.0),
  and LDAP/OAuth moved to their own Authentication page (0.10.0).
- **Archived chats** moved from the user menu into Settings (0.11.0).
- **`ENABLE_REALTIME_CHAT_SAVE` no longer does anything** (0.11.1).

Env vars renamed upstream and updated in `values.yaml` at the same time:
`ENABLE_RAG_WEB_SEARCH` → `ENABLE_WEB_SEARCH`, `RAG_WEB_SEARCH_ENGINE` →
`WEB_SEARCH_ENGINE`, `RAG_WEB_SEARCH_RESULT_COUNT` → `WEB_SEARCH_RESULT_COUNT`,
`ENABLE_SEARCH_QUERY` → `ENABLE_SEARCH_QUERY_GENERATION`. These are PersistentConfig
settings, so the database copy wins after first boot — renaming them matters for a
fresh reprovision, not for the running instance.

This chart stays on the **standard** image. The `-slim` variant added in 0.11.4 drops
local embedding/reranking models, local Whisper, PDF/Word readers and DDGS, and
requires PostgreSQL + pgvector for knowledge search — none of which suits this
SQLite-backed deployment.
