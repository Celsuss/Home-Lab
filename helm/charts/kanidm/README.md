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
