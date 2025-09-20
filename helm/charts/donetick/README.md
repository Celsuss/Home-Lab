# Donetick

## Secrets

### Create secrets
Use `openssl rand -base64 36` to generate the random strings

``` yaml
jwt:
    secret: "change_this_to_a_secure_random_string_32_characters_long" 
```

### Encrypt secrets
1. Make sure you have added `.sops.yaml` to the root of the repo with the public keys.
2. Encrypt secrets by running `sops -e -i values-secrets.yaml`.
3. Make sure you have added the private key to the argo-cd chart.
