#!/bin/bash
set -e

# Add repo
helm repo add argo-helm https://argoproj.github.io/argo-helm
helm repo update
helm dep update ../charts/argo-cd/

# Create namespace
kubectl create namespace argo-cd --dry-run=client -o=json | kubectl apply -f -

# Manage certificate for k3s
sudo cat /var/lib/rancher/k3s/server/tls/server-ca.crt > k3s-ca.crt
kubectl create secret generic k3s-ca-cert \
        --from-file=ca.crt=k3s-ca.crt \
        -n argo-cd \
        --dry-run=client \
        -o yaml | kubectl apply -f -

# Create SOPS secret
kubectl create secret generic sops-age-key \
        --from-file=keys.txt=/home/celsuss/.config/sops/age/keys.txt \
        -n argo-cd

# Deploy chart
helm dependency build ../charts/argo-cd
helm upgrade --install argo-cd ../charts/argo-cd \
     -f ../charts/argo-cd/values.yaml \
     --namespace argo-cd

echo "Argo-cd deployment complete!"
echo "Get Node ip from running 'kubectl get nodes -o wide'"
echo "Add 'NODE-IP argocd.homelab.local' to '/etc/hosts'."
echo "Username: Admin"
echo "Get password by running 'kubectl get secret argocd-initial-admin-secret -o jsonpath=\"{.data.password}\" -n argo-cd | base64 -d'"
