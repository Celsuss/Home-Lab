# Kandom

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

