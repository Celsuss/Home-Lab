# Open Terminal

[Open Terminal](https://github.com/open-webui/open-terminal) is a self-hosted shell, filesystem and
code-execution sandbox exposed over a REST/WebSocket API. Open WebUI proxies it and hands the model
tools to run commands, read and write files, preview ports and produce artifacts — which is what
turns the chat UI into an agent harness rather than a question-answering box.

Deployed into `ai-workloads` beside `open-webui` and `ollama`. **ClusterIP only, no Ingress:** the
connection is configured at the admin level, so every request is proxied by the Open WebUI backend
and nothing else ever needs to reach port 8000.

## Manual steps

### 1. Vault secrets (before first sync)

```bash
# Open Terminal's own bearer key (pin it — the image auto-generates one otherwise)
vault kv put secret/homelab/open-terminal api-key="$(openssl rand -hex 32)"

# Open WebUI admin API key for the PostSync job.
# Mint it once in the UI: profile menu → Settings → Account → API keys → Create (sk-...)
vault kv patch secret/homelab/open-webui admin-api-key="sk-..."
```

`vault kv patch` preserves `webui-secret-key`. The existing `open-webui` VaultStaticSecret refreshes
every 60s, so no Open WebUI restart is needed.

### 2. Model settings (after first sync)

Open Terminal needs tool calling. Open WebUI 0.10.0+ defaults models to **Native** function calling;
if the terminal tools are never invoked, check Workspace → Models → *model* → Advanced.

## How the Open WebUI connection is configured

Open WebUI stores terminal connections in its database under `terminal_server.connections`. The
`TERMINAL_SERVER_CONNECTIONS` env var only *seeds* that key when it is absent, and this instance
seeded it as `[]` the first time it booted on 0.11.4 — so the env var is useless here, exactly like
`TOOL_SERVER_CONNECTIONS` (see `helm/charts/open-webui/README.md`).

Instead, `templates/configure-openwebui-job.yaml` runs as an ArgoCD **PostSync** hook and reconciles
the connection over the admin API (`POST /api/v1/configs/terminal_servers`). It:

- waits for Open WebUI's `/health`,
- reads the current connection list,
- replaces only the entry whose id is `open-terminal`, leaving any other connection untouched,
- does nothing at all when the entry already matches (no audit-log churn on every sync).

**Git owns that entry.** Changes made to the Open Terminal connection in Settings → Admin →
Integrations are reverted on the next sync; change `values.yaml` instead. Set
`openWebui.enabled: false` to manage it by hand.

## Security model

The image gives its `user` account passwordless sudo, so the model is effectively root *inside the
container* — that is the sandbox design, not a misconfiguration. What actually bounds it is at pod
level:

- `automountServiceAccountToken: false` — no Kubernetes API credentials.
- A NetworkPolicy (`networkPolicy.enabled`, default on): ingress only from `app: open-webui` on 8000;
  egress only to cluster DNS and the public internet. RFC1918 is excluded, so the LAN
  (192.168.0.0/24), the pod CIDR and the service CIDR are unreachable — Vault, the router and other
  namespaces included.
- No host path mounts and no Docker socket (mounting the socket would be root on the host).

The pod deliberately has **no** restrictive container `securityContext`: the entrypoint needs sudo to
chown the mounted workspace and runs a `setcap`'d Python binary, so `drop: ALL` or a read-only root
filesystem breaks startup.

Upstream's `OPEN_TERMINAL_ALLOWED_DOMAINS` egress allowlist is not used — it needs `NET_ADMIN` in the
pod and would break `pip install` from anything not listed. The NetworkPolicy covers the case that
matters here (reaching back into the homelab).

## Storage

`/home/user` is a 20Gi RWO PVC on the K3s `local-path` provisioner. It is **not** backed up by
volsync — it is agent scratch space. If real work starts living there, add a tier-2 entry to
`helm/charts/volsync-backups/values.yaml` for `open-terminal-pvc`.

## Notes

- Image variant: the **full** image (~1.4 GB compressed, ~4 GB on disk) — Python 3.12, Node 22, git,
  build tools, pandoc, LaTeX, LibreOffice, ffmpeg, pandas/numpy/matplotlib, docker CLI. The `-slim`
  tag drops all of it (and sudo) if the pod ever needs to get small.
- `packages.apt` / `packages.pip` / `packages.npm` install on **every** container start, so anything
  put there is re-downloaded on every restart. Prefer letting the agent install into the workspace.
- Context pressure: Open Terminal injects its tool schemas plus the workspace `AGENTS.md` into every
  turn on top of Open WebUI's built-in tool preamble. That is the mechanism behind the one-character
  replies documented in `helm/charts/ollama/values.yaml`. If replies degrade, check
  `usage.prompt_eval_count`, then raise `OLLAMA_CONTEXT_LENGTH` above 16384 or drive the terminal
  with `qwen2.5-coder:14b` instead of `gemma4:e4b-it-q8_0`.
