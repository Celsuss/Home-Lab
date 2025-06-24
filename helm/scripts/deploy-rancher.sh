#!/bin/bash
set -e

# Add the Rancher Helm repository
helm repo add rancher-stable https://releases.rancher.com/server-charts/stable

helm repo update

# Create namespace for Rancher
kubectl create namespace cattle-system --dry-run=client -o yaml | kubectl apply -f -

# Install cert-manager (required for Rancher)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.12.0/cert-manager.yaml

# Wait for cert-manager to be ready
echo "Waiting for cert-manager to be ready..."
kubectl wait --for=condition=available deployment/cert-manager -n cert-manager --timeout=120s
kubectl wait --for=condition=available deployment/cert-manager-webhook -n cert-manager --timeout=120s

# Install Rancher using our values file
helm upgrade --install rancher rancher-stable/rancher \
     --namespace cattle-system \
     --values ./charts/rancher/values.yaml \
     --wait

echo "Rancher deployment complete!"
echo "Add this to your hosts file: \$(minikube ip) rancher.minikube.local"
