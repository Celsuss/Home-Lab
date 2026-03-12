# ArgoCD

## Deploy
helm upgrade --install argo-cd . \
     -f values.yaml \
     --namespace argo-cd


## OAuth2/OIDC Clients

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
