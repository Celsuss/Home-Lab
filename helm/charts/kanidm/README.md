# Kanidm

## Post deployment setup

> **Important:** Steps 1-3 must be completed before the provisioning job can
> succeed. The job runs as a Helm post-install hook and will fail with
> `AuthenticationFailed` if the `idm_admin` password is not yet in Vault.

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

## User Provisioning

After the initial setup above, the chart includes an automated provisioning Job
that creates users and groups on each deploy. It runs as a Helm post-install/post-upgrade hook.

**Prerequisites:**
- The `idm_admin` password must be stored in Vault at `secret/kanidm/idm_admin`
  with a `password` key (step 3 above).
- The Vault Secrets Operator must be running so the `VaultStaticSecret` can sync
  the password into a Kubernetes Secret.

**What gets provisioned (configurable in `values.yaml`):**
- Groups: `idm_admins`, `sso_users`
- User: `celsus` (member of both groups)

The provisioning script is idempotent — re-running it will skip existing users/groups.

## Troubleshooting

### `AuthenticationFailed` error in provisioning job

If the provisioning job logs show `AuthenticationFailed` or the kanidm server
logs show `account has no available credentials`, the `idm_admin` account has no
credentials set in the kanidm database. This happens after initial deployment or
whenever the database PVC is recreated.

**Fix:**
1. Re-run `recover-account` to set credentials in the kanidm DB (step 2 in Post deployment setup)
2. Store the new password in Vault (step 3)
3. Delete the failed job so ArgoCD recreates it:
```
kubectl delete job kanidm-provision-users -n kanidm
```

### TLS certificate errors from provisioning job

The TLS cert SAN includes both `kanidm.homelab.local` and the internal service
DNS (`kanidm.kanidm.svc.cluster.local`). The init container automatically
detects SAN mismatches and regenerates certs on pod restart — no manual
intervention needed. If you change the domain or namespace, simply restart the
statefulset:
```
kubectl rollout restart statefulset/kanidm -n kanidm
```
