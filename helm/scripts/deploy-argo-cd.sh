#!/bin/bash
set -e

# Add repo
helm repo add argo-helm https://argoproj.github.io/argo-helm
helm repo update
helm dep update charts/argo-cd/

# Create namespace
kubectl create namespace argo-cd --dry-run=client -o=json | kubectl apply -f -

helm dependency build ../charts/argo-cd
helm upgrade --install argo-cd ../charts/argo-cd \
     -f ../charts/argo-cd/values.yaml \
     --namespace argo-cd

echo "Argo-cd deployment complete!"
echo "Run 'kubectl port-forward svc/argo-cd-argocd-server 8080:443 -n argo-cd' to enable access to UI."
echo "Username: Admin"
echo "Get password by running 'kubectl get secret argocd-initial-admin-secret -o jsonpath=\"{.data.password}\" -n argo-cd | base64 -d'"
echo "Go to http://localhost:8080"
