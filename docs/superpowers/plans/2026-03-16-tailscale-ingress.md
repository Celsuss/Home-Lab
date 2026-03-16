# Tailscale Ingress Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable remote access to all homelab services via Tailscale MagicDNS (`*.ts.net`) using a shared Helm library chart pattern.

**Architecture:** A `homelab-common` library chart provides a reusable Tailscale Ingress template. App charts declare it as a dependency and opt in via `tailscale.enabled: true`. Hostname fields are standardized to `ingress.host` across all charts first.

**Tech Stack:** Helm (library charts, `file://` dependencies), Tailscale Operator (IngressClass), K3s/ArgoCD

**Spec:** `docs/superpowers/specs/2026-03-16-tailscale-ingress-design.md`

---

## Chunk 1: Foundation — Library Chart

### Task 1: Create `homelab-common` library chart scaffold

**Files:**
- Create: `helm/charts/homelab-common/Chart.yaml`
- Create: `helm/charts/homelab-common/templates/_tailscale-ingress.tpl`

- [ ] **Step 1: Create Chart.yaml**

```yaml
---
apiVersion: v2
name: homelab-common
description: Shared Helm library chart for homelab infrastructure templates
type: library
version: 0.1.0
```

- [ ] **Step 2: Create the Tailscale Ingress template**

Create `helm/charts/homelab-common/templates/_tailscale-ingress.tpl`:

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
                name: {{ .serviceName | default (.Values.tailscale.serviceName | default .fullname) }}
                port:
                  number: {{ .servicePort | default (.Values.tailscale.servicePort | default .Values.service.port) }}
{{- end }}
{{- end }}
```

The service backend supports three override levels:
1. **Dict-level** (`.serviceName`/`.servicePort`) — for dynamic values computed in the template call (e.g., khoj's `{{ fullname }}-server`)
2. **Values-level** (`.Values.tailscale.serviceName`/`.servicePort`) — for static overrides in values.yaml (e.g., karakeep, audiobookshelf)
3. **Default** (`.fullname` / `.Values.service.port`) — standard pattern

- [ ] **Step 3: Lint the library chart**

Run: `helm lint helm/charts/homelab-common`
Expected: PASS (with info about icon being recommended)

- [ ] **Step 4: Commit**

```bash
git add helm/charts/homelab-common/
git commit -m "feat: add homelab-common library chart with Tailscale Ingress template"
```

### Task 2: Verify library chart works with one app chart (uptime-kuma)

This is a dry-run integration test before touching all charts. We temporarily add the dependency to uptime-kuma and verify `helm template` renders correctly.

**Files:**
- Modify: `helm/charts/uptime-kuma/Chart.yaml`
- Create: `helm/charts/uptime-kuma/templates/ingress-tailscale.yaml`
- Modify: `helm/charts/uptime-kuma/values.yaml`

- [ ] **Step 1: Add homelab-common dependency to uptime-kuma Chart.yaml**

Add to `helm/charts/uptime-kuma/Chart.yaml`:

```yaml
dependencies:
  - name: homelab-common
    version: 0.1.0
    repository: "file://../homelab-common"
```

- [ ] **Step 2: Run helm dependency update**

Run: `helm dependency update helm/charts/uptime-kuma`
Expected: `Saving 1 charts` / `Deleting outdated charts` — a `charts/homelab-common-0.1.0.tgz` file appears.

- [ ] **Step 3: Create ingress-tailscale.yaml template**

Create `helm/charts/uptime-kuma/templates/ingress-tailscale.yaml`:

```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "uptime-kuma.fullname" .) "labels" (include "uptime-kuma.labels" . | trim) "namespace" .Values.namespace) }}
```

- [ ] **Step 4: Add tailscale values to uptime-kuma values.yaml**

Add to end of `helm/charts/uptime-kuma/values.yaml`:

```yaml
tailscale:
  enabled: false
```

- [ ] **Step 5: Verify template renders with tailscale disabled**

Run: `helm template test helm/charts/uptime-kuma --namespace monitoring`
Expected: No Tailscale Ingress in output. Only the existing Traefik Ingress appears.

- [ ] **Step 6: Verify template renders with tailscale enabled**

Run: `helm template test helm/charts/uptime-kuma --namespace monitoring --set tailscale.enabled=true`
Expected: Output includes a second Ingress with `ingressClassName: tailscale`, name `test-uptime-kuma-tailscale-ingress`, host `"test-uptime-kuma"`, service port `3001`.

- [ ] **Step 7: Verify helm lint passes**

Run: `helm lint helm/charts/uptime-kuma`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add helm/charts/uptime-kuma/
git commit -m "feat: integrate homelab-common library chart with uptime-kuma (tailscale disabled by default)"
```

---

## Chunk 2: Hostname Standardization — `hostName` → `host` (7 charts)

These charts use `ingress.hostName`. Change to `ingress.host` in both `values.yaml` and `templates/ingress.yaml`.

### Task 3: Standardize audiobookshelf ingress hostname

**Files:**
- Modify: `helm/charts/audiobookshelf/values.yaml`
- Modify: `helm/charts/audiobookshelf/templates/ingress.yaml`

- [ ] **Step 1: Rename `hostName` to `host` in values.yaml**

In `helm/charts/audiobookshelf/values.yaml`, change:
```yaml
  hostName: audiobookshelf.homelab.local
```
to:
```yaml
  host: audiobookshelf.homelab.local
```

- [ ] **Step 2: Update template to use `ingress.host`**

In `helm/charts/audiobookshelf/templates/ingress.yaml`, replace all occurrences of `.Values.ingress.hostName` with `.Values.ingress.host`.

- [ ] **Step 3: Verify**

Run: `helm template test helm/charts/audiobookshelf --namespace media | grep "host:"`
Expected: `- host: audiobookshelf.homelab.local`

### Task 4: Standardize beszel ingress hostname

**Files:**
- Modify: `helm/charts/beszel/values.yaml`
- Modify: `helm/charts/beszel/templates/ingress.yaml`

- [ ] **Step 1:** Same pattern as Task 3 — rename `hostName` → `host` in values.yaml and template.

- [ ] **Step 2: Verify**

Run: `helm template test helm/charts/beszel | grep "host:"`
Expected: Contains `beszel.homelab.local`

### Task 5: Standardize ezbookkeeping ingress hostname

**Files:**
- Modify: `helm/charts/ezbookkeeping/values.yaml`
- Modify: `helm/charts/ezbookkeeping/templates/ingress.yaml`

- [ ] **Step 1:** Rename `hostName` → `host` in values.yaml and template.

- [ ] **Step 2: Verify**

Run: `helm template test helm/charts/ezbookkeeping | grep "host:"`
Expected: Contains `ezbookkeeping.homelab.local`

### Task 6: Standardize glance ingress hostname

**Files:**
- Modify: `helm/charts/glance/values.yaml`
- Modify: `helm/charts/glance/templates/ingress.yaml`

- [ ] **Step 1:** Rename `hostName` → `host` in values.yaml and template.

- [ ] **Step 2: Verify**

Run: `helm template test helm/charts/glance | grep "host:"`
Expected: Contains `glance.homelab.local`

### Task 7: Standardize karakeep ingress hostname

**Files:**
- Modify: `helm/charts/karakeep/values.yaml`
- Modify: `helm/charts/karakeep/templates/ingress.yaml`
- Modify: `helm/charts/karakeep/templates/NOTES.txt`

- [ ] **Step 1:** Rename `hostName` → `host` in values.yaml and template.

- [ ] **Step 2: Update NOTES.txt**

In `helm/charts/karakeep/templates/NOTES.txt`, replace the `hosts[]` iteration block (lines 2-7):
```
{{- if .Values.ingress.enabled }}
{{- range $host := .Values.ingress.hosts }}
  {{- range .paths }}
  http{{ if $.Values.ingress.tls }}s{{ end }}://{{ $host.host }}{{ .path }}
  {{- end }}
{{- end }}
```
with:
```
{{- if .Values.ingress.enabled }}
  http{{ if .Values.ingress.tls }}s{{ end }}://{{ .Values.ingress.host }}
```

- [ ] **Step 3: Verify**

Run: `helm template test helm/charts/karakeep --namespace karakeep | grep "host:"`
Expected: Contains `karakeep.homelab.local`

### Task 8: Standardize open-webui ingress hostname

**Files:**
- Modify: `helm/charts/open-webui/values.yaml`
- Modify: `helm/charts/open-webui/templates/ingress.yaml`

- [ ] **Step 1:** Rename `hostName` → `host` in values.yaml and template.

- [ ] **Step 2: Verify**

Run: `helm template test helm/charts/open-webui | grep "host:"`
Expected: Contains `open-webui.homelab.local`

### Task 9: Commit all `hostName` → `host` changes

- [ ] **Step 1: Lint all modified charts**

Run: `for chart in audiobookshelf beszel ezbookkeeping glance karakeep open-webui uptime-kuma; do echo "--- $chart ---"; helm lint helm/charts/$chart; done`
Expected: All pass

- [ ] **Step 2: Commit**

```bash
git add helm/charts/audiobookshelf helm/charts/beszel helm/charts/ezbookkeeping helm/charts/glance helm/charts/karakeep helm/charts/open-webui
git commit -m "refactor: standardize ingress.hostName to ingress.host across 6 charts"
```

Note: uptime-kuma's `hostName` → `host` rename is deferred to Task 21 (Chunk 5) since Task 2 already modified the chart for library integration. The rename is done separately to keep the library integration commit clean.

---

## Chunk 3: Hostname Standardization — `hosts[]` → `host` (5 charts)

These charts use `ingress.hosts[]` (array of objects). Flatten to `ingress.host` (single string).

### Task 10: Standardize donetick ingress

**Files:**
- Modify: `helm/charts/donetick/values.yaml`
- Modify: `helm/charts/donetick/templates/ingress.yaml`

- [ ] **Step 1: Flatten hosts[] to host in values.yaml**

In `helm/charts/donetick/values.yaml`, replace:
```yaml
  hosts:
    - host: donetick.homelab.local
      paths:
        - path: /
          pathType: ImplementationSpecific
```
with:
```yaml
  host: donetick.homelab.local
```

- [ ] **Step 2: Simplify ingress template**

Replace the rules section in `helm/charts/donetick/templates/ingress.yaml`. The current template iterates over `hosts[]` and `paths[]`. Replace with single-host pattern:

```yaml
  rules:
    - host: {{ .Values.ingress.host | quote }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ include "donetick.fullname" . }}
                port:
                  number: {{ .Values.service.port }}
```

- [ ] **Step 3: Verify**

Run: `helm template test helm/charts/donetick --namespace utils | grep "host:"`
Expected: Contains `donetick.homelab.local`

### Task 11: Standardize forgejo ingress

**Files:**
- Modify: `helm/charts/forgejo/values.yaml`
- Modify: `helm/charts/forgejo/templates/ingress.yaml`
- Modify: `helm/charts/forgejo/templates/NOTES.txt`

- [ ] **Step 1: Flatten hosts[] to host in values.yaml**

Same pattern as Task 10 — replace `hosts:` array with `host: forgejo.homelab.local`.

- [ ] **Step 2: Simplify ingress template**

Same pattern as Task 10 — replace `range .Values.ingress.hosts` loop with single-host block using `{{ .Values.ingress.host | quote }}`.

- [ ] **Step 3: Update NOTES.txt**

In `helm/charts/forgejo/templates/NOTES.txt`, replace the `hosts[]` iteration block (lines 16-20):
```
{{- range $host := .Values.ingress.hosts }}
  {{- range .paths }}
  http{{ if $.Values.ingress.tls }}s{{ end }}://{{ $host.host }}{{ .path }}
  {{- end }}
{{- end }}
```
with:
```
  http{{ if .Values.ingress.tls }}s{{ end }}://{{ .Values.ingress.host }}
```

- [ ] **Step 4: Verify**

Run: `helm template test helm/charts/forgejo | grep "host:"`
Expected: Contains `forgejo.homelab.local`

### Task 12: Standardize jellyfin ingress

**Files:**
- Modify: `helm/charts/jellyfin/values.yaml`
- Modify: `helm/charts/jellyfin/templates/ingress.yaml`

- [ ] **Step 1:** Same pattern as Task 10 — flatten `hosts[]` to `host` in values, simplify template.

- [ ] **Step 2: Verify**

Run: `helm template test helm/charts/jellyfin | grep "host:"`
Expected: Contains `jellyfin.homelab.local`

### Task 13: Standardize ollama ingress

**Files:**
- Modify: `helm/charts/ollama/values.yaml`
- Modify: `helm/charts/ollama/templates/ingress.yaml`

- [ ] **Step 1:** Same pattern as Task 10 — flatten `hosts[]` to `host` in values, simplify template.

Note: ollama has `ingress.enabled: false` — still standardize the field name for consistency.

- [ ] **Step 2: Verify**

Run: `helm template test helm/charts/ollama --set ingress.enabled=true | grep "host:"`
Expected: Contains `ollama.homelab.local`

### Task 14: Standardize tandoor-recipes ingress

**Files:**
- Modify: `helm/charts/tandoor-recipes/values.yaml`
- Modify: `helm/charts/tandoor-recipes/templates/ingress.yaml`

- [ ] **Step 1:** Same pattern as Task 10 — flatten `hosts[]` to `host` in values, simplify template.

- [ ] **Step 2: Verify**

Run: `helm template test helm/charts/tandoor-recipes | grep "host:"`
Expected: Contains `tandoor.homelab.local`

### Task 15: Commit all `hosts[]` → `host` changes

- [ ] **Step 1: Lint all modified charts**

Run: `for chart in donetick forgejo jellyfin ollama tandoor-recipes; do echo "--- $chart ---"; helm lint helm/charts/$chart; done`
Expected: All pass

- [ ] **Step 2: Commit**

```bash
git add helm/charts/donetick helm/charts/forgejo helm/charts/jellyfin helm/charts/ollama helm/charts/tandoor-recipes
git commit -m "refactor: standardize ingress.hosts[] to ingress.host across 5 charts"
```

---

## Chunk 4: Library Integration — All 13 App Charts

Add `homelab-common` dependency, `ingress-tailscale.yaml` template, and `tailscale` values to each chart. uptime-kuma is already done (Task 2).

### Task 16: Integrate library into `hostName`-pattern charts (6 charts)

Apply to: audiobookshelf, beszel, ezbookkeeping, glance, karakeep, open-webui

For each chart, do the following (using audiobookshelf as the example):

**Files per chart:**
- Modify: `helm/charts/<chart>/Chart.yaml`
- Create: `helm/charts/<chart>/templates/ingress-tailscale.yaml`
- Modify: `helm/charts/<chart>/values.yaml`

- [ ] **Step 1: Add dependency to Chart.yaml**

Add to each chart's `Chart.yaml`:
```yaml
dependencies:
  - name: homelab-common
    version: 0.1.0
    repository: "file://../homelab-common"
```

- [ ] **Step 2: Run helm dependency update for all 6 charts**

```bash
for chart in audiobookshelf beszel ezbookkeeping glance karakeep open-webui; do
  helm dependency update helm/charts/$chart
done
```

- [ ] **Step 3: Create ingress-tailscale.yaml for each chart**

Each chart gets a one-liner template. The chart name in the `include` calls must match the chart's `_helpers.tpl` define names.

`helm/charts/audiobookshelf/templates/ingress-tailscale.yaml`:
```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "audiobookshelf.fullname" .) "labels" (include "audiobookshelf.labels" . | trim) "namespace" .Values.namespace) }}
```

`helm/charts/beszel/templates/ingress-tailscale.yaml`:
```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "beszel.fullname" .) "labels" (include "beszel.labels" . | trim) "namespace" .Values.namespace) }}
```

`helm/charts/ezbookkeeping/templates/ingress-tailscale.yaml`:
```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "ezbookkeeping.fullname" .) "labels" (include "ezbookkeeping.labels" . | trim) "namespace" .Values.namespace) }}
```

`helm/charts/glance/templates/ingress-tailscale.yaml`:
```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "glance.fullname" .) "labels" (include "glance.labels" . | trim) "namespace" .Values.namespace) }}
```

`helm/charts/karakeep/templates/ingress-tailscale.yaml`:
```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "karakeep.fullname" .) "labels" (include "karakeep.labels" . | trim) "namespace" .Values.namespace) }}
```

`helm/charts/open-webui/templates/ingress-tailscale.yaml`:
```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "open-webui.fullname" .) "labels" (include "open-webui.labels" . | trim) "namespace" .Values.namespace) }}
```

- [ ] **Step 4: Add tailscale values to each chart**

Add to end of each chart's `values.yaml`:
```yaml
tailscale:
  enabled: false
```

**Charts needing service overrides:** These charts define their Kubernetes Service name as `.Values.name` (a plain values field), NOT `{{ include "<chart>.fullname" . }}`. Since the library template defaults the service backend to `.fullname` (which includes the release prefix, e.g., `test-audiobookshelf`), but the actual Service is just `.Values.name` (e.g., `audiobookshelf`), an explicit `serviceName` override is required.

`helm/charts/audiobookshelf/values.yaml`:
```yaml
tailscale:
  enabled: false
  serviceName: audiobookshelf
```

`helm/charts/beszel/values.yaml`:
```yaml
tailscale:
  enabled: false
  serviceName: beszel
```

`helm/charts/ezbookkeeping/values.yaml`:
```yaml
tailscale:
  enabled: false
  serviceName: ezbookkeeping
```

`helm/charts/glance/values.yaml`:
```yaml
tailscale:
  enabled: false
  serviceName: glance
```

`helm/charts/karakeep/values.yaml` — service name from `.Values.karakeep.name`, port from `.Values.karakeep.service.port`:
```yaml
tailscale:
  enabled: false
  serviceName: karakeep
  servicePort: 3000
```

`helm/charts/open-webui/values.yaml`:
```yaml
tailscale:
  enabled: false
  serviceName: open-webui
```

- [ ] **Step 5: Verify all 6 charts template correctly with tailscale disabled**

```bash
for chart in audiobookshelf beszel ezbookkeeping glance karakeep open-webui; do
  echo "--- $chart ---"
  helm template test helm/charts/$chart 2>&1 | head -5
done
```
Expected: No errors, no Tailscale Ingress in output.

- [ ] **Step 6: Verify all 6 charts template correctly with tailscale enabled**

```bash
for chart in audiobookshelf beszel ezbookkeeping glance karakeep open-webui; do
  echo "--- $chart ---"
  helm template test helm/charts/$chart --set tailscale.enabled=true 2>&1 | grep -A5 "tailscale-ingress"
done
```
Expected: Each shows a Tailscale Ingress with correct service name and port.

- [ ] **Step 7: Lint all 6 charts**

```bash
for chart in audiobookshelf beszel ezbookkeeping glance karakeep open-webui; do
  echo "--- $chart ---"
  helm lint helm/charts/$chart
done
```
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add helm/charts/audiobookshelf helm/charts/beszel helm/charts/ezbookkeeping helm/charts/glance helm/charts/karakeep helm/charts/open-webui
git commit -m "feat: add Tailscale Ingress support to 6 charts via homelab-common library"
```

### Task 17: Integrate library into `hosts[]`-pattern charts (5 charts)

Apply to: donetick, forgejo, jellyfin, ollama, tandoor-recipes

- [ ] **Step 1: Add dependency to each Chart.yaml**

Same dependency block as Task 16, Step 1.

- [ ] **Step 2: Run helm dependency update**

```bash
for chart in donetick forgejo jellyfin ollama tandoor-recipes; do
  helm dependency update helm/charts/$chart
done
```

- [ ] **Step 3: Create ingress-tailscale.yaml for each chart**

`helm/charts/donetick/templates/ingress-tailscale.yaml`:
```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "donetick.fullname" .) "labels" (include "donetick.labels" . | trim) "namespace" .Values.namespace) }}
```

`helm/charts/forgejo/templates/ingress-tailscale.yaml`:
```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "forgejo.fullname" .) "labels" (include "forgejo.labels" . | trim) "namespace" .Values.namespace) }}
```

`helm/charts/jellyfin/templates/ingress-tailscale.yaml`:
```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "jellyfin.fullname" .) "labels" (include "jellyfin.labels" . | trim) "namespace" .Values.namespace) }}
```

`helm/charts/ollama/templates/ingress-tailscale.yaml`:
```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "ollama.fullname" .) "labels" (include "ollama.labels" . | trim) "namespace" .Values.namespace) }}
```

`helm/charts/tandoor-recipes/templates/ingress-tailscale.yaml`:
```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "tandoor-recipes.fullname" .) "labels" (include "tandoor-recipes.labels" . | trim) "namespace" .Values.namespace) }}
```

- [ ] **Step 4: Add tailscale values**

Add `tailscale.enabled: false` to each chart's values.yaml. No service overrides needed for this group (all use standard fullname/service.port pattern).

- [ ] **Step 5: Verify with tailscale disabled**

```bash
for chart in donetick forgejo jellyfin ollama tandoor-recipes; do
  echo "--- $chart ---"
  helm template test helm/charts/$chart 2>&1 | head -5
done
```
Expected: No errors, no Tailscale Ingress.

- [ ] **Step 6: Verify with tailscale enabled**

```bash
for chart in donetick forgejo jellyfin ollama tandoor-recipes; do
  echo "--- $chart ---"
  helm template test helm/charts/$chart --set tailscale.enabled=true --set ingress.enabled=true 2>&1 | grep -A5 "tailscale-ingress"
done
```
Expected: Each shows Tailscale Ingress.

- [ ] **Step 7: Lint and commit**

```bash
for chart in donetick forgejo jellyfin ollama tandoor-recipes; do helm lint helm/charts/$chart; done
git add helm/charts/donetick helm/charts/forgejo helm/charts/jellyfin helm/charts/ollama helm/charts/tandoor-recipes
git commit -m "feat: add Tailscale Ingress support to 5 charts via homelab-common library"
```

### Task 18: Integrate library into khoj (special case)

Khoj uses non-standard service name (`khoj-server`) and port path (`khoj.service.port`).

**Files:**
- Modify: `helm/charts/khoj/Chart.yaml`
- Create: `helm/charts/khoj/templates/ingress-tailscale.yaml`
- Modify: `helm/charts/khoj/values.yaml`

- [ ] **Step 1: Add dependency**

Add homelab-common dependency to `helm/charts/khoj/Chart.yaml`.

- [ ] **Step 2: Run helm dependency update**

Run: `helm dependency update helm/charts/khoj`

- [ ] **Step 3: Create ingress-tailscale.yaml**

Create `helm/charts/khoj/templates/ingress-tailscale.yaml`. Khoj is a special case: its service name is `{{ include "khoj.fullname" . }}-server` and its port is at `.Values.khoj.service.port`. We construct the service name dynamically in the template call rather than using a static override, so it works correctly regardless of release name:

```yaml
{{- $serviceName := printf "%s-server" (include "khoj.fullname" .) -}}
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "khoj.fullname" .) "labels" (include "khoj.labels" . | trim) "namespace" .Values.namespace "serviceName" $serviceName "servicePort" .Values.khoj.service.port) }}
```

This requires a small update to the library template to check for `serviceName` and `servicePort` passed directly in the dict (not just via `.Values.tailscale`). See **Step 3a** below.

- [ ] **Step 3a: Update library template to support dict-level overrides**

In `helm/charts/homelab-common/templates/_tailscale-ingress.tpl`, update the service backend to prefer dict-level overrides over values-level overrides:

```yaml
            backend:
              service:
                name: {{ .serviceName | default (.Values.tailscale.serviceName | default .fullname) }}
                port:
                  number: {{ .servicePort | default (.Values.tailscale.servicePort | default .Values.service.port) }}
```

This allows charts to pass `serviceName`/`servicePort` directly in the dict call (for dynamic values like khoj) or via `values.yaml` (for static values like karakeep).

- [ ] **Step 4: Add tailscale values**

Add to `helm/charts/khoj/values.yaml`:
```yaml
tailscale:
  enabled: false
```

Note: No `serviceName`/`servicePort` overrides needed in values.yaml — they are computed dynamically in the template call (Step 3).

- [ ] **Step 5: Verify**

Run: `helm template test helm/charts/khoj --namespace ai-workloads --set tailscale.enabled=true`
Expected: Tailscale Ingress with `name: test-khoj-tailscale-ingress`, service name `test-khoj-server`, port `8000`.

- [ ] **Step 6: Lint and commit**

```bash
helm lint helm/charts/khoj
git add helm/charts/khoj
git commit -m "feat: add Tailscale Ingress support to khoj with service name override"
```

---

## Chunk 5: Enable and Validate

### Task 19: Enable Tailscale Ingress on uptime-kuma (pilot)

**Files:**
- Modify: `helm/charts/uptime-kuma/values.yaml`

**Prerequisites (manual, Tailscale admin console):**
- Verify OAuth client has `devices` and `dns` write scopes at https://login.tailscale.com/admin/settings/oauth
- Verify ACL tags permit operator to create new devices

- [ ] **Step 1: Verify IngressClass exists in cluster**

Run: `kubectl get ingressclass tailscale`
Expected: IngressClass `tailscale` exists. If not, check the Tailscale operator logs: `kubectl logs -n tailscale -l app.kubernetes.io/name=operator`

- [ ] **Step 2: Enable tailscale for uptime-kuma**

In `helm/charts/uptime-kuma/values.yaml`, change:
```yaml
tailscale:
  enabled: false
```
to:
```yaml
tailscale:
  enabled: true
```

- [ ] **Step 3: Commit and push**

```bash
git add helm/charts/uptime-kuma/values.yaml
git commit -m "feat: enable Tailscale Ingress for uptime-kuma (pilot)"
git push
```

- [ ] **Step 4: Wait for ArgoCD sync and verify**

Check ArgoCD has synced the change, then verify:

Run: `kubectl get ingress -n monitoring`
Expected: Two ingresses — the existing Traefik one and a new `*-tailscale-ingress`.

Run: `kubectl get ingress -n monitoring -o wide`
Expected: The Tailscale ingress shows `CLASS: tailscale`.

- [ ] **Step 5: Verify MagicDNS hostname**

Check the Tailscale admin console (https://login.tailscale.com/admin/machines) for a new device. Note the `*.ts.net` hostname.

Test from phone (connected to Tailscale): open `https://<hostname>.ts.net` in a browser.
Expected: Uptime Kuma loads with valid HTTPS.

### Task 20: Enable Tailscale Ingress for remaining charts

Only proceed after Task 19 is validated.

- [ ] **Step 1: Enable tailscale for all remaining charts**

Set `tailscale.enabled: true` in values.yaml for: audiobookshelf, beszel, donetick, ezbookkeeping, forgejo, glance, jellyfin, karakeep, khoj, ollama, open-webui, tandoor-recipes.

- [ ] **Step 2: Commit and push**

```bash
git add helm/charts/*/values.yaml
git commit -m "feat: enable Tailscale Ingress for all app charts"
git push
```

- [ ] **Step 3: Verify all ingresses created**

Run: `kubectl get ingress --all-namespaces | grep tailscale`
Expected: One Tailscale Ingress per enabled chart.

- [ ] **Step 4: Spot-check 2-3 services from phone**

Test from phone: access ArgoCD, Jellyfin, and one other service via their `*.ts.net` hostnames.
Expected: All load with valid HTTPS.

### Task 21: Update uptime-kuma hostName → host (deferred from Chunk 2)

Uptime-kuma was integrated with the library in Task 2 before hostname standardization. Now standardize its hostname field.

**Files:**
- Modify: `helm/charts/uptime-kuma/values.yaml`
- Modify: `helm/charts/uptime-kuma/templates/ingress.yaml`

- [ ] **Step 1: Rename hostName to host in values.yaml**

Change `hostName: uptime-kuma.homelab.local` to `host: uptime-kuma.homelab.local`.

- [ ] **Step 2: Update ingress template**

Replace `.Values.ingress.hostName` with `.Values.ingress.host` in `templates/ingress.yaml`.

- [ ] **Step 3: Verify and commit**

```bash
helm lint helm/charts/uptime-kuma
helm template test helm/charts/uptime-kuma --namespace monitoring | grep "host:"
git add helm/charts/uptime-kuma
git commit -m "refactor: standardize uptime-kuma ingress.hostName to ingress.host"
```
