# Khoj AI second brain

## Secrets
### Create secrets
Use `openssl rand -base64 36` to generate the random strings

POSTGRES_PASSWORD: "secret-string"
KHOJ_ADMIN_PASSWORD: "very-secret-string"
KHOJ_DJANGO_SECRET_KEY: "super-secret-string"

### Encrypt secrets
1. Make sure you have added `.sops.yaml` to the root of the repo with the public keys.
2. Encrypt secrets by running `sops -e -i values-secrets.yaml`.
3. Make sure you have added the private key to the argo-cd chart.
