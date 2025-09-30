
# Tailscale

## Create secrets

### Encrypt secrets
1. Make sure you have added `.sops.yaml` to the root of the repo with the public keys.
2. Encrypt secrets by running `sops -e -i values-secrets.yaml`.
3. Make sure you have added the private key to the argo-cd chart.
