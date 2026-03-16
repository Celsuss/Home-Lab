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
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .fullname }}-tailscale
  namespace: {{ .namespace }}
  labels:
    {{- .labels | nindent 4 }}
spec:
  ingressClassName: tailscale
  tls:
    - hosts:
        - {{ .fullname }}
  rules:
    - host: {{ .fullname }}
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

### 4. Tailscale Operator Configuration

The upstream `tailscale-operator` chart automatically registers the `tailscale` IngressClass when deployed. No Helm config changes needed.

**Manual prerequisite (Tailscale admin console):**
- The operator's OAuth client must have `devices` and `dns` write scopes
- ACL tags must permit the operator to create new devices (one per Ingress)
- Verify at https://login.tailscale.com/admin/settings/oauth

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

## Rollout Plan

### Phase 1: Foundation
- Create `homelab-common` library chart
- Verify Tailscale operator OAuth scopes support IngressClass

### Phase 2: Hostname Standardization
- Normalize all 12 charts to `ingress.host` (single string)
- Update templates, values.yaml, NOTES.txt
- No functional change — same Traefik ingress behavior

### Phase 3: Library Integration
- Add `homelab-common` dependency to all 13 standard app charts
- Add `ingress-tailscale.yaml` template to each
- Add `tailscale.enabled: false` to each values.yaml

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
