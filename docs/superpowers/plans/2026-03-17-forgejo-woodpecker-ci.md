# Forgejo + Woodpecker CI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy Forgejo (git server) and Woodpecker CI as wrapper Helm charts with Vault secrets, Tailscale ingress, and ArgoCD GitOps integration.

**Architecture:** Two independent wrapper charts — `forgejo` wraps the upstream Forgejo Helm chart (v16.2.1, OCI) with PostgreSQL subchart, `woodpecker` wraps the upstream Woodpecker chart (v3.5.1, OCI) with Kubernetes backend. Both use Vault + VSO for secrets and homelab-common for Tailscale ingress.

**Tech Stack:** Helm 3, Kubernetes (K3s), ArgoCD, HashiCorp Vault + VSO, Tailscale, Traefik, cert-manager

**Spec:** `docs/superpowers/specs/2026-03-17-forgejo-woodpecker-ci-design.md`

---

## Chunk 1: Cleanup and Forgejo Chart

### Task 1: Remove old gitea chart and root-app CR

**Files:**
- Delete: `helm/charts/gitea/` (entire directory)
- Modify: `helm/charts/root-app/templates/gitea-app.yaml`

- [ ] **Step 1: Delete the gitea chart directory**

```bash
rm -rf helm/charts/gitea
```

- [ ] **Step 2: Replace gitea-app.yaml with forgejo-app.yaml**

Delete `helm/charts/root-app/templates/gitea-app.yaml` and create `helm/charts/root-app/templates/forgejo-app.yaml`:

```yaml
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: forgejo-app
  namespace: argo-cd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/Celsuss/Home-Lab.git
    path: helm/charts/forgejo
    targetRevision: HEAD
    helm:
      valueFiles:
        - values.yaml
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: forgejo
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

- [ ] **Step 3: Commit**

```bash
git rm -r helm/charts/gitea
git rm helm/charts/root-app/templates/gitea-app.yaml
git add helm/charts/root-app/templates/forgejo-app.yaml
git commit -m "chore: remove old gitea chart, add forgejo ArgoCD application"
```

---

### Task 2: Create Forgejo wrapper chart scaffolding

**Files:**
- Delete: all files in `helm/charts/forgejo/` (replace standalone with wrapper)
- Create: `helm/charts/forgejo/Chart.yaml`
- Create: `helm/charts/forgejo/values.yaml`
- Create: `helm/charts/forgejo/templates/_helpers.tpl`

- [ ] **Step 1: Delete all existing forgejo chart files**

```bash
rm -rf helm/charts/forgejo/*
```

- [ ] **Step 2: Create Chart.yaml**

Create `helm/charts/forgejo/Chart.yaml`:

```yaml
---
apiVersion: v2
name: forgejo
description: A Helm chart to deploy Forgejo git service
type: application
version: 0.1.0
appVersion: "14.0.1"

dependencies:
  - name: forgejo
    version: "16.2.1"
    repository: "oci://code.forgejo.org/forgejo-helm"
  - name: homelab-common
    version: 0.1.0
    repository: "file://../homelab-common"
```

- [ ] **Step 3: Create values.yaml**

Create `helm/charts/forgejo/values.yaml`:

```yaml
---
namespace: forgejo

forgejo:
  fullnameOverride: forgejo
  gitea:
    admin:
      existingSecret: forgejo-admin-secret
    config:
      database:
        DB_TYPE: postgres
        HOST: forgejo-postgresql.forgejo.svc.cluster.local:5432
        NAME: forgejo
        USER: forgejo
      server:
        DOMAIN: forgejo.homelab.local
        ROOT_URL: https://forgejo.homelab.local
      webhook:
        ALLOWED_HOST_LIST: external,loopback
  persistence:
    enabled: true
    storageClass: local-path
    size: 10Gi
  ingress:
    enabled: true
    className: traefik
    hosts:
      - host: forgejo.homelab.local
        paths:
          - path: /
            pathType: Prefix
    tls:
      - secretName: forgejo-tls
        hosts:
          - forgejo.homelab.local
    annotations:
      cert-manager.io/cluster-issuer: homelab-ca
  postgresql:
    enabled: true
    auth:
      existingSecret: forgejo-admin-secret
      secretKeys:
        adminPasswordKey: postgres-password
        userPasswordKey: postgres-password
    primary:
      persistence:
        storageClass: local-path

tailscale:
  enabled: true
  serviceName: forgejo-http
  servicePort: 3000

vault:
  secretPath: homelab/forgejo
  secretName: forgejo-admin-secret
```

- [ ] **Step 4: Create _helpers.tpl**

Create `helm/charts/forgejo/templates/_helpers.tpl`:

```
{{/*
Expand the name of the chart.
*/}}
{{- define "forgejo.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "forgejo.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "forgejo.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "forgejo.labels" -}}
helm.sh/chart: {{ include "forgejo.chart" . }}
{{ include "forgejo.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "forgejo.selectorLabels" -}}
app.kubernetes.io/name: {{ include "forgejo.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

- [ ] **Step 5: Commit scaffolding**

```bash
git add helm/charts/forgejo/
git commit -m "feat: scaffold forgejo wrapper chart with upstream dependency"
```

---

### Task 3: Add Forgejo Vault and Tailscale templates

**Files:**
- Create: `helm/charts/forgejo/templates/vault-auth.yaml`
- Create: `helm/charts/forgejo/templates/serviceaccount-vso.yaml`
- Create: `helm/charts/forgejo/templates/vault-static-secret.yaml`
- Create: `helm/charts/forgejo/templates/ingress-tailscale.yaml`

- [ ] **Step 1: Create vault-auth.yaml**

Create `helm/charts/forgejo/templates/vault-auth.yaml`:

```yaml
---
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultAuth
metadata:
  name: default
  namespace: {{ .Values.namespace }}
spec:
  method: kubernetes
  mount: kubernetes
  kubernetes:
    role: vso-role
    serviceAccount: vso-service-account
```

- [ ] **Step 2: Create serviceaccount-vso.yaml**

Create `helm/charts/forgejo/templates/serviceaccount-vso.yaml`:

```yaml
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: vso-service-account
  namespace: {{ .Values.namespace }}
```

- [ ] **Step 3: Create vault-static-secret.yaml**

Create `helm/charts/forgejo/templates/vault-static-secret.yaml`:

```yaml
---
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultStaticSecret
metadata:
  name: forgejo-vss
  namespace: {{ .Values.namespace }}
spec:
  vaultAuthRef: default
  mount: secret
  type: kv-v2
  path: {{ .Values.vault.secretPath }}
  refreshAfter: 60s
  destination:
    create: true
    name: {{ .Values.vault.secretName }}
    overwrite: true
```

- [ ] **Step 4: Create ingress-tailscale.yaml**

Create `helm/charts/forgejo/templates/ingress-tailscale.yaml`:

```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "forgejo.fullname" .) "labels" (include "forgejo.labels" . | trim) "namespace" .Values.namespace) }}
```

- [ ] **Step 5: Run helm dependency update and lint**

```bash
helm dependency update helm/charts/forgejo
helm lint helm/charts/forgejo
```

Expected: dependencies downloaded, lint passes with 0 failures.

- [ ] **Step 6: Run helm template to verify rendering**

```bash
helm template forgejo helm/charts/forgejo --namespace forgejo
```

Expected: renders all upstream Forgejo resources plus custom vault-auth, serviceaccount-vso, vault-static-secret, and tailscale ingress templates.

- [ ] **Step 7: Commit**

```bash
git add helm/charts/forgejo/
git commit -m "feat: add Vault secrets and Tailscale ingress to forgejo chart"
```

---

## Chunk 2: Woodpecker Chart

### Task 4: Create Woodpecker wrapper chart scaffolding

**Files:**
- Create: `helm/charts/woodpecker/Chart.yaml`
- Create: `helm/charts/woodpecker/values.yaml`
- Create: `helm/charts/woodpecker/templates/_helpers.tpl`

- [ ] **Step 1: Create Chart.yaml**

Create `helm/charts/woodpecker/Chart.yaml`:

```yaml
---
apiVersion: v2
name: woodpecker
description: A Helm chart to deploy Woodpecker CI with Forgejo integration
type: application
version: 0.1.0
appVersion: "3.13.0"

dependencies:
  - name: woodpecker
    version: "3.5.1"
    repository: "oci://ghcr.io/woodpecker-ci/helm"
  - name: homelab-common
    version: 0.1.0
    repository: "file://../homelab-common"
```

- [ ] **Step 2: Create values.yaml**

Create `helm/charts/woodpecker/values.yaml`:

```yaml
---
namespace: woodpecker

woodpecker:
  server:
    enabled: true
    env:
      WOODPECKER_HOST: https://woodpecker.homelab.local
      WOODPECKER_FORGEJO: "true"
      WOODPECKER_FORGEJO_URL: http://forgejo-http.forgejo.svc.cluster.local:3000
      WOODPECKER_ADMIN: <forgejo-admin-username>
    extraSecretNamesForEnvFrom:
      - woodpecker-secret
    ingress:
      enabled: true
      ingressClassName: traefik
      hosts:
        - host: woodpecker.homelab.local
      annotations:
        cert-manager.io/cluster-issuer: homelab-ca
    persistentVolume:
      enabled: true
      storageClass: local-path
      size: 5Gi

  agent:
    enabled: true
    env:
      WOODPECKER_BACKEND: kubernetes
      WOODPECKER_BACKEND_K8S_NAMESPACE: woodpecker
      WOODPECKER_BACKEND_K8S_STORAGE_CLASS: local-path
      WOODPECKER_BACKEND_K8S_VOLUME_SIZE: 1G
    extraSecretNamesForEnvFrom:
      - woodpecker-secret
    replicaCount: 1

tailscale:
  enabled: true
  serviceName: woodpecker-server
  servicePort: 8000

vault:
  secretPath: homelab/woodpecker
  secretName: woodpecker-secret
```

- [ ] **Step 3: Create _helpers.tpl**

Create `helm/charts/woodpecker/templates/_helpers.tpl`:

```
{{/*
Expand the name of the chart.
*/}}
{{- define "woodpecker.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "woodpecker.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "woodpecker.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "woodpecker.labels" -}}
helm.sh/chart: {{ include "woodpecker.chart" . }}
{{ include "woodpecker.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "woodpecker.selectorLabels" -}}
app.kubernetes.io/name: {{ include "woodpecker.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

- [ ] **Step 4: Commit scaffolding**

```bash
git add helm/charts/woodpecker/
git commit -m "feat: scaffold woodpecker wrapper chart with upstream dependency"
```

---

### Task 5: Add Woodpecker Vault, Tailscale templates and ArgoCD app

**Files:**
- Create: `helm/charts/woodpecker/templates/vault-auth.yaml`
- Create: `helm/charts/woodpecker/templates/serviceaccount-vso.yaml`
- Create: `helm/charts/woodpecker/templates/vault-static-secret.yaml`
- Create: `helm/charts/woodpecker/templates/ingress-tailscale.yaml`
- Create: `helm/charts/root-app/templates/woodpecker-app.yaml`

- [ ] **Step 1: Create vault-auth.yaml**

Create `helm/charts/woodpecker/templates/vault-auth.yaml`:

```yaml
---
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultAuth
metadata:
  name: default
  namespace: {{ .Values.namespace }}
spec:
  method: kubernetes
  mount: kubernetes
  kubernetes:
    role: vso-role
    serviceAccount: vso-service-account
```

- [ ] **Step 2: Create serviceaccount-vso.yaml**

Create `helm/charts/woodpecker/templates/serviceaccount-vso.yaml`:

```yaml
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: vso-service-account
  namespace: {{ .Values.namespace }}
```

- [ ] **Step 3: Create vault-static-secret.yaml**

Create `helm/charts/woodpecker/templates/vault-static-secret.yaml`:

```yaml
---
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultStaticSecret
metadata:
  name: woodpecker-vss
  namespace: {{ .Values.namespace }}
spec:
  vaultAuthRef: default
  mount: secret
  type: kv-v2
  path: {{ .Values.vault.secretPath }}
  refreshAfter: 60s
  destination:
    create: true
    name: {{ .Values.vault.secretName }}
    overwrite: true
```

- [ ] **Step 4: Create ingress-tailscale.yaml**

Create `helm/charts/woodpecker/templates/ingress-tailscale.yaml`:

```yaml
{{ include "homelab-common.tailscale-ingress" (dict "Values" .Values "fullname" (include "woodpecker.fullname" .) "labels" (include "woodpecker.labels" . | trim) "namespace" .Values.namespace) }}
```

- [ ] **Step 5: Create woodpecker-app.yaml in root-app**

Create `helm/charts/root-app/templates/woodpecker-app.yaml`:

```yaml
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: woodpecker-app
  namespace: argo-cd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/Celsuss/Home-Lab.git
    path: helm/charts/woodpecker
    targetRevision: HEAD
    helm:
      valueFiles:
        - values.yaml
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: woodpecker
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

- [ ] **Step 6: Run helm dependency update and lint**

```bash
helm dependency update helm/charts/woodpecker
helm lint helm/charts/woodpecker
```

Expected: dependencies downloaded, lint passes with 0 failures.

- [ ] **Step 7: Run helm template to verify rendering**

```bash
helm template woodpecker helm/charts/woodpecker --namespace woodpecker
```

Expected: renders upstream Woodpecker server + agent resources plus custom vault-auth, serviceaccount-vso, vault-static-secret, and tailscale ingress templates.

- [ ] **Step 8: Lint root-app to verify new application CRs**

```bash
helm lint helm/charts/root-app
helm template helm/charts/root-app --namespace argo-cd
```

Expected: lint passes, template output includes forgejo-app and woodpecker-app Application CRs.

- [ ] **Step 9: Commit**

```bash
git add helm/charts/woodpecker/ helm/charts/root-app/templates/woodpecker-app.yaml
git commit -m "feat: add Vault secrets, Tailscale ingress, and ArgoCD app for woodpecker"
```

---

## Chunk 3: Validation and Final Commit

### Task 6: End-to-end validation

**Files:** None (validation only)

- [ ] **Step 1: Lint all charts**

```bash
helm lint helm/charts/forgejo
helm lint helm/charts/woodpecker
helm lint helm/charts/root-app
```

Expected: all pass with 0 failures.

- [ ] **Step 2: Template all charts with namespace**

```bash
helm template forgejo helm/charts/forgejo --namespace forgejo > /dev/null
helm template woodpecker helm/charts/woodpecker --namespace woodpecker > /dev/null
helm template root-app helm/charts/root-app --namespace argo-cd > /dev/null
```

Expected: all render successfully with exit code 0.

- [ ] **Step 3: Verify Forgejo chart renders Vault resources**

```bash
helm template forgejo helm/charts/forgejo --namespace forgejo | grep -A5 "kind: VaultAuth"
helm template forgejo helm/charts/forgejo --namespace forgejo | grep -A5 "kind: VaultStaticSecret"
helm template forgejo helm/charts/forgejo --namespace forgejo | grep -A3 "kind: ServiceAccount"
```

Expected: VaultAuth with `namespace: forgejo`, VaultStaticSecret with `path: homelab/forgejo` and `name: forgejo-admin-secret`, ServiceAccount `vso-service-account` in `forgejo` namespace.

- [ ] **Step 4: Verify Woodpecker chart renders Vault resources**

```bash
helm template woodpecker helm/charts/woodpecker --namespace woodpecker | grep -A5 "kind: VaultAuth"
helm template woodpecker helm/charts/woodpecker --namespace woodpecker | grep -A5 "kind: VaultStaticSecret"
helm template woodpecker helm/charts/woodpecker --namespace woodpecker | grep -A3 "kind: ServiceAccount"
```

Expected: VaultAuth with `namespace: woodpecker`, VaultStaticSecret with `path: homelab/woodpecker` and `name: woodpecker-secret`, ServiceAccount `vso-service-account` in `woodpecker` namespace.

- [ ] **Step 5: Verify Tailscale ingress renders for both charts with correct ports**

```bash
helm template forgejo helm/charts/forgejo --namespace forgejo | grep -A15 "ingressClassName: tailscale"
helm template woodpecker helm/charts/woodpecker --namespace woodpecker | grep -A15 "ingressClassName: tailscale"
```

Expected: Tailscale Ingress resources with correct hostnames, service names (`forgejo-http`, `woodpecker-server`), and port numbers (3000, 8000).

- [ ] **Step 6: Dry-run install both charts**

```bash
helm install test-forgejo helm/charts/forgejo --dry-run --namespace forgejo
helm install test-woodpecker helm/charts/woodpecker --dry-run --namespace woodpecker
```

Expected: both render successfully with no errors.

---

## Post-Implementation: Manual Deployment Steps

These steps are performed by the user after the code is pushed to `main`:

1. **Create Forgejo Vault secrets:**
   ```bash
   vault kv put secret/homelab/forgejo \
     username=<admin-user> \
     password=<admin-pass> \
     email=<admin-email> \
     postgres-password=<db-pass>
   ```

2. **Wait for ArgoCD to sync Forgejo** — verify pods are running in `forgejo` namespace.

3. **Create Forgejo OAuth2 app** — In Forgejo UI: Settings > Applications > Create OAuth2 Application
   - Application name: `Woodpecker CI`
   - Redirect URI: `https://woodpecker.homelab.local/authorize`
   - Note the Client ID and Client Secret

4. **Create Woodpecker Vault secrets:**
   ```bash
   vault kv put secret/homelab/woodpecker \
     WOODPECKER_FORGEJO_CLIENT=<client-id-from-step-3> \
     WOODPECKER_FORGEJO_SECRET=<client-secret-from-step-3> \
     WOODPECKER_AGENT_SECRET=$(openssl rand -hex 32)
   ```

5. **Wait for ArgoCD to sync Woodpecker** — verify pods are running in `woodpecker` namespace.

6. **Verify** — Navigate to `https://woodpecker.homelab.local`, log in via Forgejo OAuth, activate a repo, trigger a test pipeline.
