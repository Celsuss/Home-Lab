# homelab-mcp

A small MCP server that gives the assistant tools for homelab services. **Home
Assistant** (Ollama conversation agent) and **Open WebUI** both use it over
Streamable HTTP. The source is in `docker/homelab-mcp/` and the image is
`ghcr.io/celsuss/homelab-mcp`.

Endpoint (cluster-internal only, no ingress):

```
http://homelab-mcp.ai-workloads.svc.cluster.local:8000/mcp
```

## Tools

| Tool | Backend | Registered when |
|---|---|---|
| `web_search(query)` | SearXNG JSON API | `SEARXNG_URL` set |
| `fetch_page(url)` | the page itself, main text via trafilatura, truncated to 4000 chars | `FETCH_ENABLED=1` |
| `add_chore(name, due_date?)` | Donetick `POST /eapi/v1/chore` | `DONETICK_URL` + `DONETICK_TOKEN` |
| `list_chores()` | Donetick `GET /eapi/v1/chore` | same |
| `search_recipes(query?)` | Tandoor `GET /api/recipe/?query=` (empty or "all" lists everything, up to 30, with the total count) | `TANDOOR_URL` + `TANDOOR_TOKEN` |
| `get_recipe(recipe_id)` | Tandoor `GET /api/recipe/{id}/` | same |
| `calendar_agenda(start_date?, days=1)` | Proton Calendar share link (ICS), cached `CALENDAR_CACHE_SECONDS` | `PROTON_ICS_URL` |

Design rules. Keep them when adding tools:

- **Lean schemas.** HA sends every tool schema to the model on every Assist
  request, and the model is a small local one. Keep each docstring to one
  sentence and the arguments flat. Tools are registered with
  `structured_output=False` so results aren't sent twice. The whole
  `tools/list` is about 1.5 KB.
- **Read or add only.** No delete, update or complete tools. This is
  guardrail 5.4 of `HOME-ASSISTANT-AI-PLAN.md`.
- **Missing config means a missing tool, not a broken one.** If a token isn't
  set, those tools aren't registered.
- **Failures come back as one readable line**, e.g. `list_chores failed: HTTP
  401 from …`, so the model can say what went wrong.
- **`fetch_page` only reaches public addresses.** It checks every redirect hop
  in `server.py`, and the NetworkPolicy only allows egress to non-RFC1918
  ranges on 80/443.

## Secrets

The Vault path is `secret/homelab/homelab-mcp`. The VaultStaticSecret syncs it
into `homelab-mcp-secrets`, which is mounted `optional`. The pod starts without
it, but then only has search and fetch. VSO rolls the Deployment whenever the
secret changes.

| Key | Where to get it |
|---|---|
| `DONETICK_TOKEN` | Donetick → Settings → Access tokens → create |
| `TANDOOR_TOKEN` | Tandoor → Settings → API → new token (scope `read`) |
| `PROTON_ICS_URL` | Proton Calendar (web) → Settings → Calendars → the calendar → Share with anyone → **Full view** → copy link |

```bash
vault kv put secret/homelab/homelab-mcp DONETICK_TOKEN=<donetick-token> TANDOOR_TOKEN=<tandoor-token>
# Add one key without touching the others:
vault kv patch secret/homelab/homelab-mcp PROTON_ICS_URL='<proton-share-link>'
```

## Calendar (Proton)

Proton Calendar has no API and no CalDAV, so `calendar_agenda` reads the
calendar's official **Full view share link**, which serves the calendar as ICS.
The plan and the rejected alternatives are in
`docs/plans/2026-10-12-proton-calendar.md`.

- **The link is a password.** It contains the key that decrypts the calendar.
  It lives only in Vault. httpx request logging is turned off in `server.py`
  for this reason, and errors only name the host.
- **Read-only, and up to 8 hours behind.** Proton refreshes the shared feed
  slowly, so an event created a minute ago may be missing. The server reuses a
  fetched copy for 15 minutes and falls back to the last good copy when a
  refresh fails.
- **Times** are rendered in `CALENDAR_TZ`. Recurring events are expanded,
  cancelled ones hidden. `start_date` takes `YYYY-MM-DD`, `today`, `tomorrow`
  or a weekday name, so small models don't have to do date arithmetic.

**If the link leaks, or to rotate it:** Proton → Settings → Calendars → the
calendar → the link → *Delete link*. Every copy stops working at once. Create a
new Full view link and `vault kv patch` it as above. VSO rolls the pod.

## Access control

There is **no auth on the MCP endpoint** because HA's MCP client has no
static-header option. The NetworkPolicy is the access control:

- **Ingress** only from the `app: open-webui` pod and from the node, because
  Home Assistant runs with `hostNetwork`. The node is listed as `10.42.0.1`
  (cni0) and `192.168.0.142`.
- **Egress** only to DNS, the SearXNG, Donetick and Tandoor pods (pod
  selector + container port, never a Service VIP), and public internet on
  80/443.

kube-router REJECTs blocked traffic, so a blocked connection fails **at once**
(curl error 7). A timeout means a rule isn't matching.

## Registering clients

**Home Assistant:** Settings → Devices & services → Add integration → **Model
Context Protocol** → URL as above. Then, under Ollama integration → Configure,
tick the new MCP API **next to** "Assist" under *Control Home Assistant / LLM
APIs*. The full steps are in `helm/charts/home-assistant/README.md` → "Homelab
tools (MCP)".

**After adding a tool or a token, reload HA's MCP integration** (Settings →
Devices & services → Model Context Protocol → ⋮ → Reload). HA keeps the tool
list it fetched when it connected, so a new tool stays invisible to the model
until then. The model then answers without calling it. The symptom is no
`tools/call` session in this server's log. 2026-10-12: `calendar_agenda` was
missing this way because homelab-mcp restarted (Vault patch) after HA did.

**Open WebUI:** Admin → Settings → External Tools → **+** → type **MCP
(Streamable HTTP)**, the same URL, auth None. Then enable it for the model
(Workspace → Models → the model → Tools → homelab) or per chat.

The type defaults to **OpenAPI**, and Open WebUI doesn't show an error when
it's wrong. The symptom is `GET /mcp/openapi.json 404` from the open-webui pod
in this server's log, and the model never sees the tools. It then reaches for
calendar/memory tools or `ask_user` instead. Changing the type on an existing
entry didn't save in 0.11.4, so delete the entry and recreate it. Working
looks like `POST /mcp 200` from the open-webui pod IP. Open WebUI's own `search_web` and
`fetch_url` stay on. `web_search`/`fetch_page` here are extras, which you can
disable per tool if the duplicates confuse a model.

## Verify

From the host (Service ClusterIP; `svc.cluster.local` doesn't resolve outside
the cluster):

```bash
IP=$(kubectl -n ai-workloads get svc homelab-mcp -o jsonpath='{.spec.clusterIP}')
curl -s "http://$IP:8000/healthz"
curl -s "http://$IP:8000/mcp" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[].name'
```

`/healthz` lists the registered tools. Expect all seven once the Vault tokens
and the calendar link exist.

## Local development

```bash
cd docker/homelab-mcp
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt
SEARXNG_URL=http://<searxng-clusterip>:8080 PORT=8765 .venv/bin/python server.py
npx @modelcontextprotocol/inspector   # connect to http://localhost:8765/mcp
```

Change dependencies in `requirements.in` and re-lock with the `uv pip compile`
line at the top of the `Dockerfile`.

## History: why not mcpo + upstream servers

This chart replaces `mcpo` (an MCP → OpenAPI proxy for Open WebUI), which was
deleted on 2026-10-12. On 2026-09-23 it was running yet serving zero tools,
with three faults stacked:

1. **Dependencies resolved at pod start.** `config.json` ran `uvx
   mcp-server-memory`, but that package doesn't exist on PyPI (memory is
   npm-only), and `uvx mcp-server-fetch` also produced no tool schemas. The
   pod looked healthy while `/<server>/openapi.json` reported `"paths": {}`.
   **Lesson: bake dependencies into a pinned image.** A registry hiccup at
   start-up gives you a running pod that silently serves nothing.
2. **Wrong base URL in Open WebUI.** It had `/openapi.json` appended, and Open
   WebUI appends its own.
3. **Registered as the wrong kind of server.** mcpo is an OpenAPI endpoint,
   not an MCP one, so "Verify connection" in Open WebUI's MCP section could
   never succeed.

homelab-mcp avoids all three. It's a real MCP endpoint with a pinned image,
and `/healthz` lists the tools actually registered.
