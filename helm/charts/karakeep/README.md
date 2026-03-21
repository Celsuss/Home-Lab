# Karakeep

## Secrets

Secrets are managed via Vault and synced by the Vault Secrets Operator.

### Store secrets in Vault
```bash
vault kv put secret/homelab/karakeep \
  NEXTAUTH_SECRET="$(openssl rand -base64 32)" \
  MEILI_MASTER_KEY="$(openssl rand -base64 32)" \
  NEXT_PUBLIC_SECRET="$(openssl rand -base64 32)"
```

The `VaultStaticSecret` CR syncs the Vault path to a Kubernetes Secret named `karakeep-secrets`. The deployment references this secret via `envFrom.secretRef`.
