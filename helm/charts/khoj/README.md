# Khoj AI second brain

## Secrets

Secrets are managed via Vault and synced by the Vault Secrets Operator.

### Store secrets in Vault
```bash
vault kv put secret/homelab/khoj \
  POSTGRES_PASSWORD="$(openssl rand -base64 32)" \
  KHOJ_ADMIN_PASSWORD="$(openssl rand -base64 32)" \
  KHOJ_DJANGO_SECRET_KEY="$(openssl rand -base64 32)"
```

The `VaultStaticSecret` CR syncs the Vault path to a Kubernetes Secret named `khoj-secrets`.

**Note:** Changing `POSTGRES_PASSWORD` requires either resetting the postgres PVC or manually updating the password inside the postgres instance first.
