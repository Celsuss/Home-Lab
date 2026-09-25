# openhands (OpenHands Agent Canvas)

A browser UI for an AI software engineer: describe a task, and an agent plans it,
edits files, runs commands and iterates. Deployed as upstream's **all-in-one
`agent-canvas` image** (React frontend + agent-server + automation server behind
one proxy on port 8000).

Inference is **not** paid for with API credits. OpenHands delegates to Claude
Code over ACP, and Claude Code authenticates with the homelab owner's Claude
subscription.

## Read this first: how the subscription billing works

OpenHands can either call an LLM API itself, or act as an *ACP client* — spawning
a locally-running coding agent over the Agent Client Protocol and delegating the
whole job to it. This chart uses the second mode with the built-in **Claude Code**
preset:

```
agent-server  →  npx -y @agentclientprotocol/claude-agent-acp  →  claude  →  api.anthropic.com
```

Claude Code does the inference and authenticates with `CLAUDE_CODE_OAUTH_TOKEN`,
a subscription token minted by `claude setup-token`. Anthropic documents that
command for exactly this case: authenticating Claude Code where no interactive
browser login is possible (CI, containers). Requires a Pro, Max, Team or
Enterprise plan.

This is deliberately **not** the widely-blogged alternative of proxying a
subscription behind an OpenAI-compatible endpoint so an arbitrary tool can
consume Anthropic models — that is prohibited. The distinction that matters: here
Claude Code *is* the agent, not a model API being impersonated.

Two consequences:

- Runs consume the **normal Claude Code subscription limits**, shared with
  terminal usage. A long unattended OpenHands run can eat a session budget.
- `CLAUDE_CODE_OAUTH_TOKEN` is a subscription-wide credential: anyone holding it
  can spend the subscription. Hence Vault, and hence the containment below.

## Containment

The agent gets a shell. Unlike classic OpenHands — which mounts
`/var/run/docker.sock` and spawns sandbox containers on the host — the all-in-one
image runs the agent's commands **inside its own container**, so no host runtime
access is needed at all.

| Boundary | How |
| --- | --- |
| Host filesystem | No `hostPath`, no `hostNetwork`, no Docker socket. The "computer" is the container. |
| Kubernetes API | `automountServiceAccountToken: false`, no ServiceAccount, no RBAC. Upstream's chart has an `rbac.*` switch that can grant this pod namespace-admin or `cluster-admin`; it is deliberately not implemented here. |
| Privileges | Non-root uid/gid 10001, `allowPrivilegeEscalation: false`, all capabilities dropped, `seccompProfile: RuntimeDefault`. |
| The LAN and the rest of the cluster | NetworkPolicy, below. |

**Do not add a `hostPath` mount to this chart.** Same rule as `cptr`: the moment
the agent can write to the node's filesystem, every other boundary here is
decorative. To work on a repo, let the agent clone it.

### NetworkPolicy

- **Ingress:** port 8000 from Traefik (`kube-system`) and the Tailscale proxy
  pods only. No other pod in `ai-workloads` can reach it.
- **Egress:** cluster DNS; Forgejo on 3000/22; and `0.0.0.0/0` with all of
  `10/8`, `172.16/12` and `192.168/16` carved out — so `api.anthropic.com`,
  `registry.npmjs.org` and GitHub work, while the LAN, the router, Vault and
  every other namespace do not.

K3s enforces policies with kube-router, which **REJECTs** rather than DROPs: a
blocked connection fails with an *instant* `curl: (7)`, never a hang. A policy is
silently inert if the controller is disabled, so verify — see below.

## Storage

One 20Gi RWO claim (`openhands-pvc`, `local-path`), mounted at three
subdirectories of `$HOME` rather than over `$HOME` itself — the image ships
dotfiles in `/home/openhands` that must not be shadowed:

| subPath | mountPath | Holds |
| --- | --- | --- |
| `openhands` | `/home/openhands/.openhands` | Settings, encrypted secrets, conversation history, event store, automation SQLite DB |
| `workspace` | `/home/openhands/workspace` | The agent's working directory: cloned repos, generated files |
| `npm` | `/home/openhands/.npm` | npm cache. The ACP preset is resolved with `npx -y` at conversation start; without this it re-downloads after every restart. Clear this subPath to pick up a newer adapter. |

Not registered with `volsync-backups`: the state is reproducible (settings are a
few UI choices; repos live in Forgejo/GitHub). Add a tier-2 entry if real work
starts accumulating in `workspace`.

## Manual steps

### 1. Mint the subscription token and put it in Vault (before the first sync)

`claude setup-token` needs an interactive browser login, so it has to be run on
the desktop, not in the cluster. The token lasts ~1 year.

```bash
claude setup-token          # copy the token it prints; it is not saved anywhere

vault kv put secret/homelab/openhands \
  claude-code-oauth-token="<token>" \
  oh-secret-key="$(openssl rand -hex 32)" \
  session-api-key="$(openssl rand -hex 32)"

vault kv get secret/homelab/openhands
```

- `oh-secret-key` → `OH_SECRET_KEY`, the settings-encryption key. Seeded from
  Vault (rather than auto-generated onto the PVC) so stored settings survive
  losing the volume.
- `session-api-key` → `OH_SESSION_API_KEYS_0`, the agent-server's API key for
  direct API calls. **Not wired up by default** (`config.sessionApiKey.enabled:
  false`) until it is confirmed that setting it does not also gate the browser
  UI. It is in Vault ready for whenever the settings-configuring hook lands.

The pod cannot start before this secret exists — `openhands-secrets` is what the
env vars reference — so do this first, or expect `CreateContainerConfigError`
until the VaultStaticSecret syncs.

### 2. Select the Claude Code agent (once, after the first sync)

In the UI: **Settings → Agent → preset "Claude Code"**. That fills the command in
as `npx -y @agentclientprotocol/claude-agent-acp` and persists `agent_kind` /
`acp_server` / `acp_command` to `~/.openhands` on the PVC, so it survives
restarts.

Leave the Secrets panel empty. A local subscription login takes priority over an
API key anyway, and `CLAUDE_CODE_OAUTH_TOKEN` from the environment is what
authenticates here.

### Token rotation (~yearly)

Expect a hard authentication failure roughly 12 months after minting, with no
graceful warning. Re-run `claude setup-token`, then:

```bash
vault kv patch secret/homelab/openhands claude-code-oauth-token="<new token>"
# VSO resyncs within 60s, but the env var is read at process start:
kubectl rollout restart -n ai-workloads deploy/openhands
```

## Access

- LAN: <https://openhands.homelab.local/canvas/>
- Tailnet: `https://openhands.<tailnet>.ts.net/canvas/`

The UI is served under **`/canvas/`**; `/api`, `/sockets` and `/alive` sit at the
root of the same port, which is why the Ingress routes `/` (Prefix) rather than
just `/canvas`. Bookmark the `/canvas/` URL — that is what the Glance tile uses.
The websocket on `/sockets` needs no Traefik annotations.

## Relationship to `cptr`

Both hand an agent a container with a shell, and both are contained the same way.
They differ in who drives:

| | `cptr` | `openhands` |
| --- | --- | --- |
| Interface | Files + editor + terminal + chat, a workstation | Task-oriented agent loop with a plan/diff view |
| Driven from | Open WebUI, as an OpenAI-compatible model provider | Its own UI (and automations) |
| Inference | Local Ollama | Claude Code, on the subscription |
| Model config | Open WebUI connection | ACP preset, no model key at all |

## Verification

```bash
helm lint helm/charts/openhands
helm template helm/charts/openhands --namespace ai-workloads
just check                              # lint + template + yamlfmt, repo-wide
```

After ArgoCD syncs:

```bash
kubectl get pods,pvc,ingress -n ai-workloads -l app.kubernetes.io/name=openhands
kubectl get vaultstaticsecret,secret openhands-secrets -n ai-workloads
```

Then, from inside the pod, confirm the egress fence is actually enforced (instant
failures, not hangs):

```bash
kubectl exec -n ai-workloads deploy/openhands -- sh -c '
  curl -s -o /dev/null -w "anthropic: %{http_code}\n" https://api.anthropic.com/ ;
  curl -s -o /dev/null -w "npm:       %{http_code}\n" https://registry.npmjs.org/ ;
  curl -s -m 5 -o /dev/null -w "LAN:       %{http_code}\n" http://192.168.0.1/ || echo "LAN: blocked (expected)"
'
```

End to end: a new conversation asking it to clone a Forgejo repo, add a test and
run it should complete with no API-key prompt, and show up against the
subscription rather than as API spend.

## Notes

- `appVersion` tracks the `ghcr.io/openhands/agent-canvas` tag. Upstream's own
  chart pins its image to the chart `appVersion` the same way.
- The image ships Node 24 and npx 11 (verified in 1.23.0), which is what makes
  the `npx`-based ACP presets work without building a custom image.
- Single replica, `strategy: Recreate` — one RWO volume holding a SQLite DB.
- Upstream's chart uses a StatefulSet with `volumeClaimTemplates`; this one uses
  a Deployment and a standalone PVC, matching every other chart here. It also
  avoids the trap upstream documents in its own template: `volumeClaimTemplates`
  is immutable, so label churn from a chart-version bump makes the apiserver
  reject the update — which under ArgoCD `selfHeal` means a stuck sync.
