# ArgoCD

## Setup SOPS
First make sure you have the correct age keys for SOPS then run the following command:
```bash
kubectl create secret generic sops-age-key \
  --from-file=keys.txt=/home/yourusername/.config/sops/age/keys.txt \
  -n argo-cd
```
