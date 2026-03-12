# Kanidm

## Post deployment setup

 1. Recover admin password:
```
 kubectl exec -n kanidm statefulset/kanidm -- \
   kanidmd recover-account -c /data/server.toml admin
```
 2. Recover idm_admin password:
```
 kubectl exec -n kanidm statefulset/kanidm -- \
   kanidmd recover-account -c /data/server.toml idm_admin
```
 3. Store passwords in Vault:
```
 vault kv put secret/kanidm/admin password=<recovered-password>
 vault kv put secret/kanidm/idm_admin password=<recovered-password>
```
 4. Accept the self-signed cert in your browser or add the CA cert to your
    system trust store. The cert is retrievable from:
```
 kubectl exec -n kanidm statefulset/kanidm -- \
   cat /data/kanidm/ca.pem
```

 5. Access Kanidm UI: https://kanidm.homelab.local

## Manual User Provisioning

Users and groups must be provisioned manually via the `kanidm` CLI. You can
run these commands from a temporary pod or from a local machine with the
kanidm CLI installed.

Install the kanidm CLI and configure `~/.config/kanidm`:

```bash
cat > ~/.config/kanidm <<EOF
uri = "https://kanidm.homelab.local"
verify_ca = false
EOF
```

### Authenticate as idm_admin

```bash
kanidm login -D idm_admin
# Enter the idm_admin password from step 2 / Vault
```

### Create groups

```bash
kanidm group create idm_admins
kanidm group create sso_users
```

### Create users and assign to groups

```bash
kanidm person create <your username> <Your Displayname>
kanidm person credential create-reset-token <your username>
kanidm group add-members idm_admins <your username>
kanidm group add-members sso_users <your username>
```

### Set a user password

```bash
kanidm person credential update celsus
```

These commands are idempotent for groups and users (creating an already-existing
entity is a no-op), but group membership additions may print a warning if the
member is already present.

## OAuth2/OIDC Clients

### ArgoCD

Run the following commands as `idm_admin` to create the ArgoCD OAuth2 client:

```bash
# Create the OAuth2 OIDC client
kanidm system oauth2 create argocd "ArgoCD" https://argocd.homelab.local

# Set the redirect URI for the OIDC callback
kanidm system oauth2 add-redirect-url argocd https://argocd.homelab.local/auth/callback

# Allow sso_users group to use this client
kanidm system oauth2 update-scope-map argocd sso_users openid profile email groups

# Use short usernames and disable PKCE (ArgoCD doesn't support it)
kanidm system oauth2 prefer-short-username argocd
kanidm system oauth2 warning-insecure-client-disable-pkce argocd

# Get the client secret and store it in Vault
kanidm system oauth2 show-basic-secret argocd
vault kv put secret/argocd/oidc client-secret=<secret-from-above>
```

## Troubleshooting

### TLS certificate issues

The TLS cert SAN includes both `kanidm.homelab.local` and the internal service
DNS (`kanidm.kanidm.svc.cluster.local`). The init container automatically
detects SAN mismatches and regenerates certs on pod restart. If you change the
domain or namespace, simply restart the statefulset:
```
kubectl rollout restart statefulset/kanidm -n kanidm
```
