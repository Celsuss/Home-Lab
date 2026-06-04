#!/bin/bash
# Extract GRPCRoute CRD from Gateway API v1.1.0 experimental channel
# (which still includes v1alpha2) and apply it to the cluster.

curl -sL https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/experimental-install.yaml | \
  python3 -c "
import sys, yaml
for d in yaml.safe_load_all(sys.stdin):
    if d and d.get('kind') == 'CustomResourceDefinition' and 'grpcroute' in d['metadata']['name']:
        yaml.dump(d, sys.stdout)
        break
" | kubectl apply --server-side --force-conflicts -f -
