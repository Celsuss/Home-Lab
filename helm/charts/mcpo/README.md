# mcpo

`mcpo` proxies stdio MCP servers as OpenAPI endpoints so Open WebUI can call
them as external tools.

## Current state: scaled to zero

`replicaCount: 0`. The chart is kept for future MCP servers, but nothing here is
in use.

Open WebUI 0.11.4 ships native `fetch_url` and memory tools, which cover both
servers `config.json` defines, so this deployment no longer earns its keep.

## Why it was failing (2026-09-23)

Web search and the "Web fetch" tool both appeared broken in Open WebUI. The
`mcpo` half of that was three separate faults stacked:

1. **Zero tools exposed.** Both sub-apps mounted but advertised no operations:

   ```console
   $ curl http://mcpo.ai-workloads.svc.cluster.local:8000/fetch/openapi.json
   {"openapi":"3.1.0","info":{"title":"fetch",...},"paths":{}}   # <- empty
   $ curl http://mcpo.ai-workloads.svc.cluster.local:8000/memory/openapi.json
   {"openapi":"3.1.0","info":{"title":"memory",...},"paths":{}}  # <- empty
   ```

   `config.json` runs `uvx mcp-server-memory`, but **that package does not exist
   on PyPI** — the memory server is npm-only
   (`npx -y @modelcontextprotocol/server-memory`). `uvx mcp-server-fetch` is a
   real package, but resolves from PyPI at pod start and was also yielding no
   tool schemas.

2. **`memory` registered with the wrong URL.** The logs showed a steady stream of
   `GET /memory/openapi.json/openapi.json → 404`: the base URL had
   `/openapi.json` on the end and Open WebUI appends its own.

3. **`fetch` registered as an MCP server.** Open WebUI 0.11 added a native MCP
   (Streamable HTTP) client, and `fetch` was registered there, so Open WebUI
   POSTed JSON-RPC straight at `/fetch` → `307` → `/fetch/` → `404`.
   **`mcpo` is an MCP → OpenAPI proxy, not an MCP endpoint.** It must be
   registered under external/OpenAPI tool servers; "Verify connection" in the
   MCP section can never succeed against it.

## Re-enabling checklist

1. Fix `config.json`. Use `npx -y <pkg>` for npm-published servers and
   `uvx <pkg>` only for real PyPI packages.
2. Prefer baking servers into a pinned image over resolving them from
   PyPI/npm at pod start — a registry hiccup otherwise yields a running pod
   that silently serves zero tools.
3. Set `replicaCount: 1`.
4. **Verify before registering** — `paths` must be non-empty:

   ```bash
   curl -s http://mcpo.ai-workloads.svc.cluster.local:8000/<server>/openapi.json \
     | jq '.paths | keys'
   ```

5. Register in Open WebUI under **external / OpenAPI tool servers**, not MCP
   servers, giving the **base** URL only
   (`http://mcpo.ai-workloads.svc.cluster.local:8000/<server>`).
