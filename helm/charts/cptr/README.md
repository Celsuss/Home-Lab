# cptr (Open WebUI Computer)

[Open WebUI Computer](https://github.com/open-webui/computer) is a browser-based Linux
workstation — files, editor, terminal, git, AI chat, coding agents — reachable from a phone
or another machine. This chart runs it in `ai-workloads` for remote work over the tailnet,
on a derived image (`docker/cptr-agents`) that adds **Claude Code**, billed to the Claude
subscription rather than API credits. See [Claude Code](#claude-code).

## Read this first: what "isolated" means here

Upstream is blunt about the threat model:

> Once authenticated, a user has full access to the host filesystem and shell, equivalent
> to an SSH session. There is no path sandboxing.

Computer is deliberately **not** a sandbox — it is a window onto the machine it runs on.
This cluster's only node is also the Arch desktop, so installing it natively (`pip install
cptr`) would put a root-equivalent shell on a personal daily-driver behind a web login.

So it runs as a **pod**, and the "computer" it exposes is the container. Consequences:

- **It is not the Arch desktop.** `~/workspace`, dotfiles and `~/.ssh` on the host are
  invisible to it. Work arrives by `git clone` and leaves by `git push`.
- Anything uncommitted on Arch is not in here.
- The cost of a compromised session is this pod's PVC — not the host.

**Do not add a `hostPath` mount to this chart.** That single line is the difference between
a contained dev box and a remote shell on your personal machine. Changing it means
revisiting the threat model, not just editing `values.yaml`.

## Containment

| Control | Effect |
|---|---|
| No `hostPath`, no host network, no Docker socket | The host filesystem is not reachable at all |
| `automountServiceAccountToken: false` | No Kubernetes API credentials — it cannot touch the cluster it runs on |
| `runAsUser/Group: 1000`, `runAsNonRoot`, `drop: [ALL]`, `allowPrivilegeEscalation: false`, `seccompProfile: RuntimeDefault` | Unprivileged even *inside* the container |
| NetworkPolicy | No LAN, no other namespaces, no Vault — see below |
| Claude subscription token | **In the pod's environment.** Anyone with a cptr login can spend the subscription — the cptr account and the tailnet are what guard it |

Unlike `open-terminal`, this image needs no `sudo` (it has none) and already runs as an
unprivileged user, so it takes a real `securityContext`. `readOnlyRootFilesystem` stays off:
`uv`, `git` and the app write under `/home/cptr` and `/tmp`.

`runAsUser` is pinned rather than inherited because the image declares `USER cptr` by
*name* — kubelet cannot verify a named user is non-root and refuses to start the pod with
`runAsNonRoot` alone. uid/gid `1000:1000` was read out of the 0.9.21 image's `/etc/passwd`.

### NetworkPolicy

Ingress on 8000 from exactly three places: the tailscale proxy pods, Traefik, and
`open-webui`. Egress: cluster DNS, `ollama:11434`, `forgejo` (3000/22), and the public
internet with **all** of RFC1918 carved out — so the LAN, the router, Vault and every other
service are unreachable.

The carve-outs are named entries under `networkPolicy.egress.allowed` in `values.yaml`; add
a service there rather than widening `blockedCIDRs`.

## Storage

One 30Gi RWO PVC, mounted twice by `subPath`:

- `data` → `/data` — SQLite `app.db`, `config.toml`, uploads, logs (`CPTR_DATA_DIR`)
- `workspace` → `/workspace` — the working directory, **and `$HOME`**

`HOME` is overridden to `/workspace` on purpose. The image's real home, `/home/cptr`, holds
the venv cptr itself runs from — mounting the PVC over it would delete the application.
Pointing `HOME` at the volume instead is what makes `~/.gitconfig`, `~/.ssh` and `gh` auth
survive a restart.

`local-path` does not enforce the 30Gi request (it is a bind mount of a directory on the
node's root filesystem), so that number is nominal — the node's disk was 88% full when this
was written.

**Backed up nightly**, tier 2 (5 daily / 2 weekly), as the `cptr` entry in
`helm/charts/volsync-backups/values.yaml` — both subPaths, since it is the whole PVC. That
includes `~/.claude` (session transcripts, settings), caches and anything installed into
`$HOME`, all encrypted by restic before it reaches Google Drive. The Claude token is not on
the volume (it is an env var from Vault). Pushed work is also in Forgejo, which is tier 1;
the backup is for what has not been pushed yet. Keep big caches (`~/.cache`, `~/.npm`,
`node_modules`) in check — VolSync's restic mover has no exclude list, so they are uploaded too.

## Manual steps

### 1. Claim the account (immediately after the first sync)

cptr prints a one-time setup URL on first boot. Until it is claimed, that link is the way
in — so do this as soon as the pod is up:

```bash
kubectl logs -n ai-workloads deploy/cptr | grep -o 'http://[^ ]*token=[a-f0-9]*'
# or just: kubectl logs -n ai-workloads deploy/cptr | head -5
```

**Do not grep for "setup".** The line is `print()`ed before logging is configured and
contains no such word — the only thing that matches is alembic's "setup plugin" noise and
the `POST /api/auth/setup` request itself.

The URL reads `http://localhost:8000/?token=...` because the CLI rewrites `0.0.0.0` to
`localhost` for display (`cptr/cli.py:25`). Replace only the host:

```
https://cptr.homelab.local/?token=<the 64 hex chars>
```

Loading the page *without* the query string and submitting the form returns **403
`invalid startup token`** (`cptr/routers/auth.py:107`) — the token is not optional, and
that is the error you get when it is missing.

The token is `secrets.token_hex(32)` generated fresh on **every process start**
(`cptr/cli.py:28`) and never persisted, so a pod restart before you claim the account
invalidates it — just re-read the logs. It cannot be pinned from the chart either: `cptr
run` overwrites `CPTR_STARTUP_TOKEN` unconditionally, and `cptr/env.py:56` `pop`s it out of
the environment. There is no pre-seeded user and no env var for one.

A failed setup attempt writes nothing (`has_any_user()` is still false), so retrying with
the right URL just works.

### 2. Mint the gateway key and put it in Vault

Needed only for the Open WebUI integration, and it has to come from the cptr UI — there is
no way to pre-seed it. In cptr: **Admin → Gateway** ("API Gateway"), type a name in
`Key name (e.g. open-webui)`, click **Create key**. The key is shown **once**
(`GET /v1/keys` returns only id/name/created_at afterwards); if you lose it, delete the key
and make another. While there, set **Response model** — gateway clients pick a *workspace*,
and this is the model Computer uses to generate the response.

```bash
vault kv put secret/homelab/cptr api-key="sk-cptr-..."
```

Then `vault.enabled: true` (already set) lets the VaultStaticSecret sync it to
`cptr-secrets`. Ignore the Base URL that panel displays — it is
`window.location.origin + /v1`, i.e. your browser's view. See below for why.

### 3. Mint the Claude Code token and put it in Vault (before the pod starts)

`claude setup-token` needs an interactive browser login, so run it on the desktop. It
prints a token valid for ~1 year and saves it nowhere. Use a **new** token rather than
openhands' — separate tokens can be revoked independently.

```bash
claude setup-token
kubectl exec -it vault-server-0 -n vault -- /bin/sh
```

Then, inside the Vault pod:

```sh
export VAULT_ADDR="http://127.0.0.1:8200"
vault login
vault kv patch secret/homelab/cptr claude-code-oauth-token=-
```

`patch`, **not** `put`: `put` replaces every key at the path and would delete `api-key`.
`=-` reads the value from stdin (paste, Enter, Ctrl-D), keeping the token out of shell
history. If the pod starts before the key exists it sits in `CreateContainerConfigError`
until VSO syncs it (≤60s), then recovers on its own.

## Access

- **LAN:** `https://cptr.homelab.local` (Traefik, `homelab-ca` cert)
- **Remote:** `https://cptr.<tailnet>.ts.net` (Tailscale operator ingress, via the shared
  `homelab-common.tailscale-ingress` helper)

Both are always on; the NetworkPolicy allows exactly those two paths.

## Relationship to `open-terminal`

They overlap but do different jobs, and both are deployed:

| | `open-terminal` | `cptr` |
|---|---|---|
| Driven by | the model (Open WebUI proxies it) | you, in a browser |
| UI | none — REST/WS API | full workstation |
| Exposure | ClusterIP, no ingress | Tailscale + Traefik |
| Image | ~1.4 GB, root-in-container, sudo | ~2 GB (`cptr-agents`), unprivileged, no sudo |

`open-terminal` is the LLM's tool backend; `cptr` is a workstation for a human. If the
duplication ever needs to go, `cptr` is the one that can absorb the other's job.

## Claude Code

### The image

`ghcr.io/celsuss/cptr-agents` is `ghcr.io/open-webui/computer` plus the tools an agent
expects; upstream ships only Python, `uv`, `git` and `gh`. Everything downloaded is pinned
by version **and** sha256 in `docker/cptr-agents/Dockerfile`:

| Group | Tools |
|---|---|
| Agent | `claude` (native binary, `/usr/local/bin`) |
| Network / data | curl, wget, jq, yq, dig, netcat, rsync |
| Search / inspect | ripgrep, fd, tree, file, less, procps, sqlite3 |
| Build | Node LTS + npm/npx, build-essential, shellcheck |
| Home-Lab repo | helm, kubeconform, just, yamlfmt — enough for `just check` before a push |

No kubectl on purpose: this pod has no cluster credentials. `npm i -g` installs to
`/workspace/.npm-global` and `uv tool install` to `/workspace/.local/bin`, both on the PVC
and both on `PATH`, so tools added at runtime survive a restart.

The chart's `image.tag` is the CI run number (`1.0.<n>`) printed by
`.github/workflows/docker-build-and-push.yml`, not the cptr version — that is the
Dockerfile's `CPTR_VERSION` ARG. A new GHCR package starts private; this one is public,
since the cluster has no pull secret.

### Updating Claude Code

The auto-updater is off (`DISABLE_AUTOUPDATER=1`; `/usr/local` is not writable by `cptr`
anyway). To bump, read the version and checksum from Anthropic's manifest, edit
`CLAUDE_VERSION` / `CLAUDE_SHA256` in the Dockerfile, push, then move `image.tag`:

```bash
v=$(curl -fsS https://downloads.claude.ai/claude-code-releases/stable)
curl -fsS "https://downloads.claude.ai/claude-code-releases/$v/manifest.json" \
  | jq -r --arg v "$v" '"CLAUDE_VERSION=\($v)\nCLAUDE_SHA256=\(.platforms["linux-x64"].checksum)"'
```

### Subscription, not API

Claude Code reads `CLAUDE_CODE_OAUTH_TOKEN` (from `cptr-secrets`, see
[Manual steps](#3-mint-the-claude-code-token-and-put-it-in-vault-before-the-pod-starts)) and
bills the subscription; `/status` inside `claude` shows which. That is within Anthropic's
terms because it is the **unmodified binary, signed in by the subscriber, used by the
subscriber**. What would not be: giving the token to Open WebUI or any other app, or
exposing this as a generic model API for other consumers. Keep the gateway reachable from
Open WebUI only (the NetworkPolicy does) and the `cptr.*` models visible to your user only.
Usage is shared with the desktop and openhands — one budget.

Env vars are read at pod start, so a rotated token needs a restart:

```bash
kubectl rollout restart -n ai-workloads deploy/cptr
```

An expired token shows up as an authentication error printed as `claude`'s *result*, not as
a crash.

### Permissions

Claude Code runs in **auto mode** (a classifier reviews each action instead of a prompt),
set in `~/.claude/settings.json` on the PVC. That is a per-volume setting, not managed from
git. The containment table above is the real boundary either way.

### Agents and the gateway

With `claude` on `PATH`, the claude code profile in **Admin → Agents** reports available.
Choosing it as the gateway's **Response model** (Admin → Gateway), or per workspace in
`.cptr/model`, makes the `cptr.<workspace>` models in Open WebUI answer with Claude Code in
that workspace.

## Open WebUI integration

cptr exposes an OpenAI-compatible gateway (`GET /v1/models`,
`POST /v1/chat/completions`), so its workspaces show up as models in Open WebUI.
`templates/configure-openwebui-job.yaml` reconciles that connection as an ArgoCD
**PostSync** hook, the same pattern as `open-terminal`.

**Git owns the entry.** Editing it in Settings → Admin → Connections is reverted on the
next sync; change `values.yaml` instead, or set `openWebui.enabled: false` to manage it by
hand.

### Why a job rather than env vars

`OPENAI_API_BASE_URLS` and friends only *seed* a fresh Open WebUI database. This instance
booted long ago, so the only way in is the admin API — exactly the problem documented for
`TOOL_SERVER_CONNECTIONS` and `TERMINAL_SERVER_CONNECTIONS`.

The endpoints are `GET /openai/config` and `POST /openai/config/update`. Probing the live
instance is the only reliable way to confirm a path exists here: **any unknown path returns
200 with the SPA's HTML**, so `/api/v1/configs/openai` *looks* like it works and does not.
A real endpoint answers `401` unauthenticated; the SPA fallback answers `200`.

### Why the job read-merges instead of posting one entry

Unlike terminal servers, OpenAI connections have **no id**. They are three parallel lists
keyed by position, plus `OPENAI_API_CONFIGS` keyed by the *stringified index*
(open-webui v0.11.4 `routers/openai.py:549`), and `update_config` replaces the lot —
dropping any config entry whose key is not a current index. So the job GETs the live lists,
finds our slot by matching `openWebui.baseUrl` exactly, edits in place or appends, and
writes everything back. Appending never shifts an existing index and nothing is ever
removed, so other providers keep their own configs. Re-running when nothing changed writes
nothing.

It also forces `ENABLE_OPENAI_API: true` — that is the provider-wide toggle, and our
connection is inert without it. Turning it on disables nothing else.

### The base URL must be the in-cluster Service

```yaml
openWebui:
  baseUrl: http://cptr.ai-workloads.svc.cluster.local:8000/v1
```

**Not** `https://cptr.homelab.local/v1`, which is what the cptr Gateway panel displays
(it is just `window.location.origin`). That route would be pod → Traefik → back in, and
Traefik is on the LAN — precisely what this chart's own egress rules deny. The Service URL
is the pod-to-pod hop the `app: open-webui` ingress rule allows.

`openWebui.headers` carries the `X-OpenWebUI-User-*` / `-Chat-Id` templates that Open WebUI
substitutes per request (`routers/openai.py:214`); cptr maps them onto its own sessions
(`cptr/routers/gateway.py:43`). `prefixId: cptr` namespaces the workspace-models in the
model list; set it to `""` to leave ids untouched.

### First sync

The hook needs `cptr-secrets` to exist, which VSO creates during the same sync. If the
first PostSync attempt fails on a missing secret, re-sync — the Job is idempotent.

## Verification

```bash
helm lint helm/charts/cptr
helm template helm/charts/cptr --namespace ai-workloads
```

After ArgoCD syncs, prove the containment from cptr's own terminal pane. **k3s enforces
policies with kube-router, which REJECTs rather than DROPs** — a blocked connection is an
*instant* `curl: (7)`, never a hang. Expecting a timeout makes a working policy look broken.

```bash
id                                                  # uid=1000(cptr) — not root
ls /host /mnt 2>&1; mount | grep -c hostPath        # no host filesystem anywhere
ls /var/run/secrets/kubernetes.io/ 2>&1             # absent — no service account token
echo $HOME; touch ~/persists-across-restarts        # /workspace, writable
```

Probe with Python rather than `curl`: it prints the elapsed milliseconds that distinguish a
REJECT from a DROP:

```bash
python3 - <<'EOF'
import socket, time
T = [("github.com", 443, "public internet", "OPEN"),
     ("ollama.ai-workloads.svc.cluster.local", 11434, "ollama (carve-out)", "OPEN"),
     ("forgejo-http.forgejo.svc.cluster.local", 3000, "forgejo (carve-out)", "OPEN"),
     ("192.168.0.1", 80, "the LAN / router", "BLOCKED"),
     ("vault-server.vault.svc.cluster.local", 8200, "other namespace", "BLOCKED"),
     ("open-terminal.ai-workloads.svc.cluster.local", 8000, "same namespace", "BLOCKED")]
for host, port, label, want in T:
    t = time.time()
    try:
        socket.create_connection((host, port), 3).close()
        got = "OPEN"
    except TimeoutError:
        got = "TIMEOUT"       # a DROP, not this cluster's REJECT — investigate
    except socket.gaierror:
        got = "DNS-FAIL"      # the DNS egress rule is broken, not the target
    except OSError:
        got = "BLOCKED"
    print(f"{'ok ' if got == want else 'XX '}{label:22} {got:8} {(time.time()-t)*1000:6.0f} ms")
EOF
```

Every `BLOCKED` row should come back in single-digit milliseconds. A `TIMEOUT` means
something other than kube-router is dropping the packet.

A `DNS-FAIL` is almost always a **wrong hostname in this test**, not a broken DNS rule: an
NXDOMAIN means the lookup was answered. If DNS egress were actually blocked, every row
would fail — `github.com` included. Check the service really is called what the probe says
(Vault's is `vault-server`, not `vault`) before suspecting the policy.

Do **not** test against the node's own IP (`192.168.0.142`): pod-to-own-node traffic is a
NetworkPolicy blind spot that CNIs commonly exempt, so it proves nothing either way.

Then the real test: clone a repo from Forgejo, edit it, commit and push — from the phone.

## Notes

- Upstream's tag (`CPTR_VERSION` in the Dockerfile) has **no `v` prefix**: `0.9.21`, not
  `v0.9.21` (which 404s on GHCR). Same trap as `open-terminal` in commit `5ee5b4c`.
- `/home/cptr` is ephemeral and the image has no sudo, so tooling that should survive a
  restart goes into `$HOME` (`/workspace`) or into the Dockerfile.
- Probes are TCP, not HTTP: upstream documents no health endpoint. Tighten if one appears.
- Upstream's `-browser` tag adds Chromium for agent browser automation; to use it, change
  the Dockerfile's `FROM`. Much larger, and the node was at 63% memory when this was written.
