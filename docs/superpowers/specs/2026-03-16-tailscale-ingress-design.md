# Tailscale Ingress Design — Remote Access to Homelab Services

## Problem

Homelab services (ArgoCD, Khoj, Jellyfin, etc.) are only accessible on the local network via `*.homelab.local` hostnames resolved by k8s-gateway and routed through Traefik. Devices on the Tailscale tailnet — such as a phone away from home — cannot resolve or reach these services, even though a Tailscale subnet router is deployed in the cluster.

## Goals

- Access all Ingress-backed homelab services from any personal Tailscale device
- Automatic TLS via Tailscale MagicDNS (`*.ts.net` hostnames)
- Production-grade: DRY templates, consistent conventions, opt-in per chart
- Avoid lock-in — keep Traefik as the primary local ingress, Tailscale as an additive layer

## Non-Goals

- Sharing services with friends/family or public internet exposure (future work)
- Replacing Traefik or the `*.homelab.local` DNS setup
- Consolidating `_helpers.tpl` into the library chart (future improvement)
- Tailscale exposure for Kanidm (IngressRouteTCP, requires different approach)
- Tailscale exposure for ArgoCD (wrapper chart, upstream manages ingress)

## Approach: Helm Library Chart + Tailscale IngressClass

Each app chart opts in to Tailscale exposure via a shared template from a `homelab-common` library chart. The Tailscale operator's IngressClass handles device registration, DNS, and TLS automatically.

### Architecture

```
Phone (Tailscale) → MagicDNS (*.ts.net) → Tailscale Ingress node → K8s Service → Pod
Laptop (local)    → k8s-gateway (*.homelab.local) → Traefik Ingress → K8s Service → Pod
```

Two parallel ingress paths to the same backend services. No interference between them.

## Design

### 1. Library Chart: `homelab-common`

**Location:** `helm/charts/homelab-common/`

**Type:** `type: library` in Chart.yaml — provides named templates, deploys no resources.

**Tailscale Ingress template** (`templates/_tailscale-ingress.tpl`):

```yaml
{{- define "homelab-common.tailscale-ingress" -}}
{{- if .Values.tailscale.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "<chart>.fullname" . }}-tailscale
  namespace: {{ .Values.namespace }}
  labels:
    {{- include "<chart>.labels" . | nindent 4 }}
spec:
  ingressClassName: tailscale
  tls:
    - hosts:
        - {{ include "<chart>.fullname" . }}
  rules:
    - host: {{ include "<chart>.fullname" . }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ .Values.tailscale.serviceName | default (include "<chart>.fullname" .) }}
                port:
                  number: {{ .Values.tailscale.servicePort | default .Values.service.port }}
{{- end }}
{{- end }}
```

**Note on label/name helpers:** Since each chart defines its own `<chart>.fullname` and `<chart>.labels`, the library template cannot directly call them. Two options:

- **Option A:** The library template accepts the fullname and labels as parameters via a dict. Each chart calls it like: `{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "khoj.fullname" .) "labels" (include "khoj.labels" .) "namespace" .Values.namespace) }}`
- **Option B:** The library defines its own `homelab-common.fullname` and `homelab-common.labels` helpers, and charts gradually adopt them.

**Decision:** Option A for now — it works without touching existing helpers, and avoids a larger refactor. Option B is the natural evolution when `_helpers.tpl` consolidation happens later.

**Actual template (Option A):**

```yaml
{{- define "homelab-common.tailscale-ingress" -}}
{{- if .Values.tailscale.enabled }}
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .fullname }}-tailscale-ingress
  namespace: {{ .namespace }}
  labels:
    {{- .labels | nindent 4 }}
spec:
  ingressClassName: tailscale
  tls:
    - hosts:
        - {{ .fullname | quote }}
  rules:
    - host: {{ .fullname | quote }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ .Values.tailscale.serviceName | default .fullname }}
                port:
                  number: {{ .Values.tailscale.servicePort | default .Values.service.port }}
{{- end }}
{{- end }}
```

**Hostname convention:** The Tailscale operator registers each Ingress as a device on the tailnet. A chart with fullname `khoj` becomes `khoj.<tailnet>.ts.net`. These device names appear in the Tailscale admin console.

**App chart usage** (e.g., `khoj/templates/ingress-tailscale.yaml`):

```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "khoj.fullname" .) "labels" (include "khoj.labels" . | trim) "namespace" .Values.namespace) }}
```

### 2. Hostname Standardization

All charts normalized to use `ingress.host` (single string field).

| Current Pattern | Charts | Change |
|----------------|--------|--------|
| `ingress.host` | khoj, kanidm | None |
| `ingress.hostName` | audiobookshelf, beszel, ezbookkeeping, glance, karakeep, open-webui, uptime-kuma | Rename field in values.yaml + template |
| `ingress.hosts[]` | donetick, forgejo, jellyfin, ollama, tandoor-recipes | Flatten to single string in values.yaml + simplify template |

No chart uses multiple hosts in practice — all `hosts[]` arrays have exactly 1 entry.

**Cross-references to update:**
- `forgejo/templates/NOTES.txt` — references `hosts[]` iteration
- `karakeep/templates/NOTES.txt` — references `hosts[]` iteration

### 3. Values Convention

Each app chart adds:

```yaml
tailscale:
  enabled: false
  # serviceName: ""   # optional, defaults to chart fullname
  # servicePort: 80   # optional, defaults to service.port
```

**Charts requiring explicit overrides:**
- **khoj** — service name is `khoj-server` (not `khoj`), so must set `tailscale.serviceName: khoj-server`
- Any chart where the service name differs from the chart fullname or where `service.port` is not at the standard values path should set `tailscale.servicePort` explicitly

### 4. Tailscale Operator Configuration

The upstream `tailscale-operator` chart creates a `tailscale` IngressClass as part of its reconciliation loop. This depends on the operator pod running with a properly configured OAuth client — if OAuth is misconfigured, the IngressClass will not be created or function.

**Manual prerequisite (Tailscale admin console):**
- The operator's OAuth client must have `devices` and `dns` write scopes — without these, IngressClass creation fails
- ACL tags must permit the operator to create new devices (one per Ingress)
- Verify at https://login.tailscale.com/admin/settings/oauth

**Capacity note:** Each Tailscale Ingress creates a separate device on the tailnet. With 13 charts enabled, that is 13 additional devices. The free Tailscale plan allows 100 devices, so this is well within limits. Rollback is simply setting `tailscale.enabled: false` — the operator cleans up the device.

**Tailscale TLS:** Tailscale automatically provisions and manages HTTPS certificates for `*.ts.net` hostnames via Let's Encrypt. No cert-manager annotations or TLS secretName are needed on the Tailscale Ingress — this is intentionally omitted from the template.

### 5. App Chart Integration

Each chart that opts in needs:

1. `Chart.yaml` — add `homelab-common` dependency:
   ```yaml
   dependencies:
     - name: homelab-common
       version: 0.1.0
       repository: "file://../homelab-common"
   ```

2. `templates/ingress-tailscale.yaml` — one-liner include:
   ```yaml
   {{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "<chart>.fullname" .) "labels" (include "<chart>.labels" . | trim) "namespace" .Values.namespace) }}
   ```

3. `values.yaml` — add tailscale toggle (default disabled)

4. Run `helm dependency update` to pull in the library chart

**ArgoCD and `file://` dependencies:** ArgoCD renders Helm charts from the Git repo. For `file://../homelab-common` to resolve, ArgoCD must have access to the parent directory. Since ArgoCD Application resources use `path: helm/charts/<chart-name>`, the repo root is already available and sibling chart references work. Verify this in Phase 1 with a dry-run before rolling out to all charts.

## Rollout Plan

### Phase 1: Foundation
- Create `homelab-common` library chart
- Verify Tailscale operator OAuth scopes support IngressClass
- Verify ArgoCD resolves `file://` chart dependencies correctly (dry-run one chart)

### Phase 2: Hostname Standardization
- Normalize all charts to `ingress.host` (single string)
- **7 charts** (audiobookshelf, beszel, ezbookkeeping, glance, karakeep, open-webui, uptime-kuma): rename `hostName` → `host`
- **5 charts** (donetick, forgejo, jellyfin, ollama, tandoor-recipes): flatten `hosts[]` → `host`
- **2 charts** (khoj, kanidm): already compliant, no changes
- Update templates, values.yaml, NOTES.txt (forgejo, karakeep)
- No functional change — same Traefik ingress behavior

### Phase 3: Library Integration
- Add `homelab-common` dependency to all 13 standard app charts (excluding kanidm, argo-cd)
- Add `ingress-tailscale.yaml` template to each
- Add `tailscale.enabled: false` to each values.yaml
- Set `tailscale.serviceName` override for khoj (`khoj-server`) and any other chart with non-standard service names

### Phase 4: Enable and Validate
- Enable on one low-risk chart (e.g., uptime-kuma): `tailscale.enabled: true`
- Verify: Tailscale Ingress created, `*.ts.net` hostname assigned, reachable from phone
- Enable for remaining charts once validated

## Out of Scope (Future Work)

- **Kanidm:** Uses IngressRouteTCP with TLS passthrough. Needs Tailscale Service proxy or a different approach.
- **ArgoCD:** Wrapper chart with upstream-managed ingress. Needs a standalone Tailscale Ingress resource in the argo-cd chart.
- **`_helpers.tpl` consolidation:** Library chart could provide shared label/name helpers. Natural evolution but not required now.
- **Friend/family access:** Tailscale node sharing or Funnel for selective public exposure.
- **Public website hosting:** Tailscale Funnel or separate ingress path with public DNS + Let's Encrypt.
