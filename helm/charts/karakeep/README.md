# Karakeep

## Secrets

### Create secrets
Use `openssl rand -base64 36` to generate the random strings

NEXTAUTH_SECRET=generated_secret
MEILI_MASTER_KEY=generated_secret
NEXT_PUBLIC_SECRET="my-super-duper-secret-string"

### Encrypt secrets
1. Make sure you have added `.sops.yaml` to the root of the repo with the public keys.
2. Encrypt secrets by running `sops -e -i values-secrets.yaml`.
3. Make sure you have added the private key to the argo-cd chart.
