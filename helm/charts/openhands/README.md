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
| Who may drive the agent | Kanidm SSO, enforced by an oauth2-proxy in front of both ingresses. See below. |

### Authentication: Kanidm SSO via oauth2-proxy

The agent-server has no user model of its own. Its session API key is injected
into the SPA shell by the static server — that is how the frontend obtains it —
so **anyone who can load the page gets the key**, and with it the full API: start
conversations, run commands in the container, and spend the Claude subscription.

So the gate is in front of the page. An **oauth2-proxy** (`openhands-auth`,
`auth.*` in `values.yaml`) terminates both ingresses and hands everything to
Kanidm before proxying on:

```
browser ──► Traefik (openhands.homelab.local)     ─┐
browser ──► Tailscale proxy (openhands.<tailnet>)  ├─► openhands-auth:4180 ──► openhands:8000
                                                   │
PostSync configure hook ───────────────────────────┴────────────────────────► openhands:8000
```

Four things about this shape are deliberate:

- **It is a separate pod, not a sidecar.** The app's NetworkPolicy carves all of
  RFC1918 out of egress; a sidecar could not reach `kanidm.homelab.local`
  (`192.168.0.142`) without a hole that would also hand the agent's shell the
  whole LAN ingress surface. The proxy pod gets its own, far narrower policy:
  DNS, the app on 8000, and one IP on one port for Kanidm.
- **The tailnet goes through it too.** Tailnet identity alone is not treated as
  sufficient to spend the subscription.
- **The `openhands` Service is untouched** on port 8000, so the PostSync
  configure hook keeps working — it just is no longer reachable from outside the
  cluster. The app's NetworkPolicy now admits *only* the proxy and that hook, so
  bypassing the gate is not a matter of knowing the Service name.
- **`--redirect-url` is unset.** oauth2-proxy derives the callback from
  `X-Forwarded-Host` per request, which is how one deployment serves both the LAN
  host and the tailnet host. Both must be registered on the Kanidm client and
  listed in `auth.oidc.whitelistDomains`.

Access control lives in **Kanidm**, not in oauth2-proxy: only the
`openhands_users` group is scope-mapped to the client, so Kanidm refuses to issue
a token to anyone else and the proxy can run with `--email-domain=*`. Setup is in
[Manual steps](#2-create-the-kanidm-client-and-group-before-the-first-sync).

Session length is the default 168h cookie. There is no `--cookie-refresh`:
Kanidm issues no refresh token without `offline_access`, so refreshing would just
force a re-login.

`auth.enabled: false` restores the pre-SSO behaviour exactly — both ingresses
point straight at the app, the NetworkPolicy readmits Traefik and the tailscale
proxy — and exists for debugging the gate, not for running that way.

Everyone who logs in still shares one agent, one PVC and one session API key;
the SSO layer says *who may drive it*, not *whose work is whose*.

**Do not add a `hostPath` mount to this chart.** Same rule as `cptr`: the moment
the agent can write to the node's filesystem, every other boundary here is
decorative. To work on a repo, let the agent clone it.

### NetworkPolicy

Two policies, one per pod.

**`openhands`** (the app):

- **Ingress:** port 8000 from the `openhands-auth` proxy and the
  `openhands-configure` hook pod — and nothing else, Traefik and the tailscale
  proxy included. (With `auth.enabled: false` those two are readmitted directly.)
- **Egress:** cluster DNS; Forgejo on 3000/22; and `0.0.0.0/0` with all of
  `10/8`, `172.16/12` and `192.168/16` carved out — so `api.anthropic.com`,
  `registry.npmjs.org` and GitHub work, while the LAN, the router, Vault and
  every other namespace do not.

**`openhands-auth`** (the proxy) — narrower in every direction except Kanidm:

- **Ingress:** port 4180 from Traefik (`kube-system`) and the Tailscale proxy
  pods.
- **Egress:** cluster DNS; the app on 8000; and `192.168.0.142:443` only — the
  Traefik LoadBalancer IP, which is how it reaches Kanidm (k8s-gateway answers
  `kanidm.homelab.local` with that address, and Traefik passes the TLS through to
  `kanidm-0`). This is the same hairpin ArgoCD's OIDC already uses. No route to
  the public internet at all.

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
- `session-api-key` → `OH_SESSION_API_KEYS_0`, the key every `/api` route wants
  in an `X-Session-API-Key` header. Seeded from Vault so the configure hook knows
  it ahead of time; without the seed the server generates one onto the PVC. It
  does **not** gate the browser UI either way — see the warning below.

The pod cannot start before this secret exists — `openhands-secrets` is what the
env vars reference — so do this first, or expect `CreateContainerConfigError`
until the VaultStaticSecret syncs.

### 2. Create the Kanidm client and group (before the first sync)

Run as `idm_admin` — see [`helm/charts/kanidm/README.md`](../kanidm/README.md)
for CLI setup and where the password lives.

```bash
kanidm login -D idm_admin

# A group of its own, not the shared sso_users: this client's token is worth
# a shell in the container and the whole Claude subscription.
kanidm group create openhands_users
kanidm group add-members openhands_users celsuss

kanidm system oauth2 create openhands "OpenHands" https://openhands.homelab.local
kanidm system oauth2 add-redirect-url openhands https://openhands.homelab.local/oauth2/callback
kanidm system oauth2 add-redirect-url openhands https://openhands.tail5517c5.ts.net/oauth2/callback
kanidm system oauth2 update-scope-map openhands openhands_users openid profile email groups
kanidm system oauth2 prefer-short-username openhands

kanidm system oauth2 show-basic-secret openhands
```

PKCE stays **on**. The argocd client had to disable it; oauth2-proxy speaks
`S256`, so there is no `warning-insecure-client-disable-pkce` here. Likewise, if
the tailnet redirect URL is rejected for an origin mismatch, add the origin —
`kanidm system oauth2 add-origin openhands https://openhands.tail5517c5.ts.net` —
rather than reaching for `disable-strict-redirect-url`.

Kanidm only emits an `email` claim if the person has `mail` set, and
oauth2-proxy wants one:

```bash
kanidm person update celsuss --mail celsuss@homelab.local
```

Then the proxy's own secret. Kept on a separate Vault path from the app's, so
the subscription token and the SSO credentials do not share a blast radius:

```bash
vault kv put secret/homelab/openhands-auth \
  client-id="openhands" \
  client-secret="<the basic secret printed above>" \
  cookie-secret="$(openssl rand -base64 32 | tr -- '+/' '-_')"

vault kv get secret/homelab/openhands-auth
```

Like `openhands-secrets`, the proxy pod cannot start before
`openhands-auth-secrets` exists — expect `CreateContainerConfigError` until the
VaultStaticSecret syncs.

### 3. Nothing — the agent selection is a PostSync hook

`configureAgent` (on by default) runs after every successful sync and pins
`agent_kind: acp`, `acp_server: claude-code` and `acp_model` through the settings
API. Git is the source of truth: switching the agent in **Settings → Agent** is
reverted on the next sync. Change `configureAgent.acpModel` in `values.yaml` to
change models.

Leave the Secrets panel empty. A local subscription login takes priority over an
API key anyway, and `CLAUDE_CODE_OAUTH_TOKEN` from the environment is what
authenticates here.

#### The settings API, as verified against 1.23.0

- `GET /api/settings` returns `agent_settings`, `conversation_settings`,
  `misc_settings` and `active_agent_profile_id`.
- `PATCH /api/settings` takes **diffs**, not whole objects:
  `{"agent_settings_diff": {"agent_kind": "acp", ...}}`. A body without one of
  the `*_diff` keys is rejected with `400`, and fields left out of the diff keep
  their values — so the hook never has to read-merge the way the cptr/Open WebUI
  hook does. It reads first only to stay quiet when nothing needs changing, and
  the active agent profile id is unaffected.
- Both calls need `X-Session-API-Key`. The hook tries `OH_SESSION_API_KEY` from
  Vault first and falls back to the key the static server injects into the SPA
  shell, so it still works if the server is honouring a key it generated onto the
  PVC before the Vault one was wired up.

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

Both redirect to Kanidm first; you need to be in the `openhands_users` group.
`/oauth2/sign_out` on either host clears the session.

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
kubectl get vaultstaticsecret -n ai-workloads
kubectl get secret openhands-secrets openhands-auth-secrets -n ai-workloads
```

`openhands-configure` reaching **Completed** is the proof the PostSync hook can
still get to port 8000 past the tightened policy.

Check the gate came up clean — an `x509: certificate signed by unknown
authority` here means the `homelab-ca-bundle` mount is wrong, not that Kanidm is
down:

```bash
kubectl logs -n ai-workloads deploy/openhands-auth | head -20
```

Then confirm the bypass really is closed. From any other pod in the namespace,
this must fail **instantly** — kube-router REJECTs, so a hang means the policy is
inert rather than working:

```bash
kubectl exec -n ai-workloads deploy/searxng -- \
  curl -s -m 5 -o /dev/null -w '%{http_code}\n' http://openhands:8000/alive \
  || echo "blocked (expected)"
```

In a browser: <https://openhands.homelab.local/> should redirect to Kanidm, and
after signing in as a member of `openhands_users` land on `/canvas/` with a
working `/sockets` websocket. Repeat from a tailnet device — if that callback
comes back as `http://` rather than `https://`, the tailscale proxy is not
setting `X-Forwarded-Proto` and `--redirect-url` has to be pinned instead.
Signing in as a person *outside* the group must be refused by Kanidm itself.

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
