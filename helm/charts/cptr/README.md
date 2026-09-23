# cptr (Open WebUI Computer)

[Open WebUI Computer](https://github.com/open-webui/computer) is a browser-based Linux
workstation — files, editor, terminal, git, AI chat, coding agents — reachable from a phone
or another machine. This chart runs it in `ai-workloads` for remote work over the tailnet.

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
was written. **Not backed up:** push work to Forgejo, which is (tier 1, `forgejo-data`). If
real work starts living in `/workspace`, add a tier-2 entry for `cptr-pvc` to
`helm/charts/volsync-backups/values.yaml`.

## Manual steps

### 1. Claim the account (immediately after the first sync)

cptr prints a one-time setup URL on first boot. Until it is claimed, that link is the way
in — so do this as soon as the pod is up:

```bash
kubectl logs -n ai-workloads deploy/cptr | grep -i -A2 setup
```

Open the URL (via `https://cptr.homelab.local` on the LAN) and create the admin account.
There is no pre-seeded user and no env var for one.

### 2. Nothing in Vault yet

`vault.enabled` is `false`. The only secret cptr needs is the API key Open WebUI would
present to it, and that key has to be minted inside the cptr UI first — see Phase 2.

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
| Image | ~1.4 GB, root-in-container, sudo | ~246 MB, unprivileged, no sudo |

`open-terminal` is the LLM's tool backend; `cptr` is a workstation for a human. If the
duplication ever needs to go, `cptr` is the one that can absorb the other's job.

## Phase 2 (not yet implemented): Open WebUI integration

cptr exposes an OpenAI-compatible gateway at `/v1/chat/completions`, so its workspaces can
appear as models in Open WebUI. The NetworkPolicy already allows `open-webui` → `cptr:8000`.

Remaining work: mint an `sk-cptr-...` key in the cptr UI, `vault kv put
secret/homelab/cptr api-key=...`, flip `vault.enabled: true`, and register the connection.
As with `open-terminal`, Open WebUI's env vars only seed a *fresh* database, so an
already-running instance has to be configured over its admin API — check
`/openapi.json` on the running 0.11.4 instance for the OpenAI-connection endpoint before
writing a PostSync job, and fall back to a one-time click in Settings → Admin → Connections
if there isn't a clean one.

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

curl -m 3 https://github.com                                        # allowed
curl -m 3 http://ollama.ai-workloads.svc.cluster.local:11434        # allowed (carve-out)
curl -m 3 http://forgejo-http.forgejo.svc.cluster.local:3000        # allowed (carve-out)
curl -m 3 http://192.168.0.1                                        # refused instantly (LAN)
curl -m 3 http://vault.vault.svc.cluster.local:8200                 # refused (other namespaces)
curl -m 3 http://open-terminal.ai-workloads.svc.cluster.local:8000  # refused (same namespace)
```

Do **not** test against the node's own IP (`192.168.0.142`): pod-to-own-node traffic is a
NetworkPolicy blind spot that CNIs commonly exempt, so it proves nothing either way.

Then the real test: clone a repo from Forgejo, edit it, commit and push — from the phone.

## Notes

- Image tag has **no `v` prefix**: `0.9.21`, not `v0.9.21` (which 404s on GHCR). Same trap
  as `open-terminal` in commit `5ee5b4c`.
- The image is Debian + Python 3.12 + `uv` + `git` + `gh`. No compilers, no Node, no sudo —
  and `/home/cptr` is ephemeral, so `uv tool install` into `$HOME` (i.e. `/workspace`) is
  the way to add tooling that survives a restart.
- Probes are TCP, not HTTP: upstream documents no health endpoint. Tighten if one appears.
- The `-browser` tag adds Chromium for agent browser automation; much larger, and the node
  was at 63% memory when this was written.
