
# Tailscale

Wrapper chart for the [Tailscale Operator](https://tailscale.com/kb/1236/kubernetes-operator) that deploys a subnet router to expose K3s cluster networks to the tailnet.

## Prerequisites

- Tailscale OAuth credentials stored in Vault
- Vault Secrets Operator running in the cluster
- A `vso-role` in Vault with a policy that allows reading `secret/data/homelab/*`

## Vault Secret Setup

Store the OAuth credentials in Vault:

```bash
vault kv put secret/homelab/tailscale client_id=<id> client_secret=<secret>
```

The Vault Secrets Operator syncs these into a Kubernetes secret named `operator-oauth` in the `tailscale` namespace. The tailscale-operator subchart is configured with `oauth.createSecret: false` so it picks up this VSO-managed secret.

## Subnet Router

The chart creates a Tailscale `Connector` resource that advertises K3s pod and service CIDRs to the tailnet:

- `10.42.0.0/16` — pod network
- `10.43.0.0/16` — service network

Configure the hostname and routes in `values.yaml` under `subnetRouter`.

## Verification

```bash
# Check VSO secret sync status
kubectl get vaultstaticsecret -n tailscale

# Verify the secret exists with correct keys
kubectl get secret operator-oauth -n tailscale -o jsonpath='{.data}' | jq

# Check operator pod is running
kubectl get pods -n tailscale
```
