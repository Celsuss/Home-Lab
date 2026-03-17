# Woodpecker CI

## Connect with Forgejo
1. Go to Forgejo: https://forgejo.homelab.local → Site Administration → Applications → Create OAuth2 Application
    - Name: Woodpecker CI
	- Redirect URI: https://woodpecker.homelab.local/authorize

2. Create the Woodpecker Vault secret with the OAuth credentials:
   ```
   vault kv put secret/homelab/woodpecker \
   WOODPECKER_FORGEJO_CLIENT=<client-id> \
   WOODPECKER_FORGEJO_SECRET=<client-secret> \
   WOODPECKER_AGENT_SECRET=$(openssl rand -hex 32)
   ```

3. Also update WOODPECKER_ADMIN in helm/charts/woodpecker/values.yaml — it currently says <forgejo-admin-username>. Replace it with the username you created in Forgejo, then push. 
