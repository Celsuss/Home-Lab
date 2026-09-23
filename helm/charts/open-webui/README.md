
# Open web UI

## Post deployment
Manual steps required before deploy:
1. Create Vault secret: `vault kv put secret/homelab/open-webui webui-secret-key=<generated-key>`
2. After deploy: In OpenWebUI Admin Settings > External Tools, add mcpo servers.
   Give the **base** URL only — Open WebUI appends `/openapi.json` itself:
  - http://mcpo.ai-workloads.svc.cluster.local:8000/fetch
  - http://mcpo.ai-workloads.svc.cluster.local:8000/memory

   (Entering the full `.../openapi.json` URL makes 0.11.x request
   `.../openapi.json/openapi.json` and the server returns 404.)

   This is a PersistentConfig setting stored in the database, so the
   `TOOL_SERVER_CONNECTIONS` env var will NOT override an existing value —
   it has to be changed in the UI.

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
