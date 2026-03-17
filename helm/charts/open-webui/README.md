
# Open web UI

## Post deployment
Manual steps required before deploy:
1. Create Vault secret: `vault kv put secret/homelab/open-webui webui-secret-key=<generated-key>`
2. After deploy: In OpenWebUI Admin Settings > External Tools, add mcpo servers:
  - http://mcpo.ai-workloads.svc.cluster.local:8000/fetch/openapi.json
  - http://mcpo.ai-workloads.svc.cluster.local:8000/memory/openapi.json
