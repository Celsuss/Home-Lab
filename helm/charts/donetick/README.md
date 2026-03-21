# Donetick

## Secrets

Secrets are managed via Vault and synced by the Vault Secrets Operator.

### Store secrets in Vault
```bash
vault kv put secret/homelab/donetick \
  jwt_secret="$(openssl rand -base64 32)"
```

The `VaultStaticSecret` CR syncs the Vault path to a Kubernetes Secret named `donetick-secrets`. The deployment injects `DT_JWT_SECRET` from this secret as an env var, which overrides the placeholder value in the ConfigMap.
