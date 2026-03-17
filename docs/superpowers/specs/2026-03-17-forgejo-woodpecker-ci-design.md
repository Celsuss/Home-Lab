# Forgejo + Woodpecker CI Design Spec

## Overview

Deploy Forgejo (git server) and Woodpecker CI (CI/CD) as two separate wrapper Helm charts in the homelab Kubernetes cluster, integrated via OAuth2. Woodpecker uses the Kubernetes backend for running pipeline pods.

**Migration note:** The existing standalone `forgejo` chart (`helm/charts/forgejo/`) and the wrapper `gitea` chart (`helm/charts/gitea/`) will both be replaced. Neither is currently deployed or working, so no data migration is needed. Both directories will be deleted and recreated (forgejo as a wrapper, gitea removed entirely).

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Forgejo        │     │  Woodpecker      │     │  Woodpecker      │
│   (wrapper)      │◄────│  Server          │     │  Agent           │
│                  │OAuth│  (wrapper)        │────►│  (K8s backend)   │
│  + PostgreSQL    │     │                  │gRPC │                  │
│    (subchart)    │     └──────────────────┘     └───────┬──────────┘
└─────────────────┘                                      │
                                                         ▼
                                                 ┌──────────────────┐
                                                 │  Pipeline Pods   │
                                                 │  (ephemeral)     │
                                                 └──────────────────┘
```

**Namespaces:** `forgejo`, `woodpecker`

**Networking:** Traefik ingress (`.homelab.local`) + Tailscale ingress for remote access on both services. Woodpecker connects to Forgejo via internal cluster URL. The exact service name depends on the upstream chart's naming — `fullnameOverride: forgejo` is set to ensure the HTTP service is named `forgejo-http`.

**Note on Woodpecker agent:** With the Kubernetes backend, the agent is a lightweight gRPC client that spawns ephemeral pipeline pods — it does not run pipelines itself.

## Forgejo Chart

**Type:** Wrapper around `oci://code.forgejo.org/forgejo-helm/forgejo` v16.2.1

**Structure:**
```
helm/charts/forgejo/
  Chart.yaml          # dependency on upstream forgejo + homelab-common
  values.yaml
  templates/
    _helpers.tpl
    ingress-tailscale.yaml
    vault-auth.yaml
    vault-static-secret.yaml
    serviceaccount-vso.yaml
```

**Key configuration:**
- `fullnameOverride: forgejo` to control service naming predictably
- PostgreSQL enabled via upstream chart's bundled postgresql subchart
- PostgreSQL password wired via `existingSecret` referencing the Vault-synced secret
- Persistence via `local-path` storage class (10Gi for git repos, default for PostgreSQL)
- Admin credentials from Vault-synced Kubernetes secret with correct key names (`username`, `password`, `email`)
- Webhook `ALLOWED_HOST_LIST: external,loopback` for Woodpecker integration
- TLS configured in ingress block alongside cert-manager annotation
- Server domain: `forgejo.homelab.local`

**values.yaml:**
```yaml
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

vault:
  secretPath: homelab/forgejo
  secretName: forgejo-admin-secret
```

**Vault secrets (key names must match upstream chart expectations):**
```bash
vault kv put secret/homelab/forgejo \
  username=<admin-user> \
  password=<admin-pass> \
  email=<admin-email> \
  postgres-password=<db-pass>
```

## Woodpecker Chart

**Type:** Wrapper around `oci://ghcr.io/woodpecker-ci/helm/woodpecker` v3.5.1

**Structure:**
```
helm/charts/woodpecker/
  Chart.yaml          # dependency on upstream woodpecker + homelab-common
  values.yaml
  templates/
    _helpers.tpl
    ingress-tailscale.yaml
    vault-auth.yaml
    vault-static-secret.yaml
    serviceaccount-vso.yaml
```

**Key configuration:**
- Server connects to Forgejo via OAuth2
- Agent uses Kubernetes backend, spawning pipeline pods in `woodpecker` namespace
- OAuth credentials and agent shared secret from Vault-synced Kubernetes secret
- SQLite for Woodpecker's own database (sufficient for homelab scale)
- Persistence via `local-path` (5Gi for server)

**values.yaml:**
```yaml
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

vault:
  secretPath: homelab/woodpecker
  secretName: woodpecker-secret
```

**Vault secrets:**
```bash
vault kv put secret/homelab/woodpecker \
  WOODPECKER_FORGEJO_CLIENT=<oauth-client-id> \
  WOODPECKER_FORGEJO_SECRET=<oauth-client-secret> \
  WOODPECKER_AGENT_SECRET=<shared-agent-secret>
```

## ArgoCD Integration

Two new Application CRs in `helm/charts/root-app/templates/`:

**`forgejo-app.yaml`:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: forgejo
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
    server: https://kubernetes.default.svc
    namespace: forgejo
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

**`woodpecker-app.yaml`:** Same pattern, `path: helm/charts/woodpecker`, `namespace: woodpecker`.

**Cleanup:** Remove existing `gitea-app.yaml` from root-app templates and delete the `helm/charts/gitea/` directory. Replace the existing standalone `helm/charts/forgejo/` with the new wrapper chart.

## Deployment Sequence

1. **Push Forgejo chart** — ArgoCD syncs. PostgreSQL and Forgejo start.
2. **Create Forgejo Vault secrets** — `vault kv put secret/homelab/forgejo ...`. VSO syncs admin credentials.
3. **Log into Forgejo** — Create OAuth2 application for Woodpecker with redirect URI `https://woodpecker.homelab.local/authorize`.
4. **Create Woodpecker Vault secrets** — `vault kv put secret/homelab/woodpecker ...` with OAuth client ID/secret and agent shared secret.
5. **Push Woodpecker chart** — ArgoCD syncs. Server connects to Forgejo, agent connects to server.
6. **Verify** — Log into Woodpecker via Forgejo OAuth, activate a repo, trigger a test pipeline.

## Implementation Notes

- All upstream chart value paths need verification against the actual chart `values.yaml` during implementation. The values shown here are best-effort based on chart documentation but may need adjustment.
- The `fullnameOverride: forgejo` ensures predictable service naming (`forgejo-http`) so Woodpecker's internal URL resolves correctly.
- Template file naming follows repo convention: `serviceaccount-vso.yaml` (not `vault-service-account.yaml`).

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Chart type | Wrapper (both) | Less maintenance, upstream charts are well-maintained |
| Chart structure | Two separate charts | Matches existing repo patterns, independent lifecycles |
| Forgejo DB | PostgreSQL (subchart) | More robust than SQLite for concurrent access |
| Woodpecker DB | SQLite | Sufficient for homelab scale, simpler |
| Woodpecker runner | Kubernetes backend | No DinD security concerns, native to cluster |
| Secrets | Vault + VSO | New project standard, no SOPS |
| Storage | local-path | Consistent with cluster, Longhorn migration planned |
| Naming | fullnameOverride | Predictable service names for cross-chart references |
