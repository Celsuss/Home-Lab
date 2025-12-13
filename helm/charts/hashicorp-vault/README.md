# Hashicorp vault helm chart

## First time deployment

### Solving Auto-Unseal

#### 1. (One-Time) Manual Initialization
This step must be performed once after the `vault-0` pod is running (but sealed).
``` bash
# Exec into the running Vault pod
kubectl exec -it vault-server-0 -n vault -- /bin/sh

# Initialize Vault. We use a 1-of-1 key for automation.
# Enterprise production would use 3-of-5 keys.[36]
vault operator init -key-shares=1 -key-threshold=1
```

This command will output one Unseal Key and one Initial Root Token. These must be saved securely.

#### 2. (One-Time) Create a Kubernetes Secret for the Unseal Key
This is the central security trade-off for this automated homelab design. The unseal key is stored in
a Base64-encoded Kubernetes `Secret`. This is necessary for the automation `CronJob` to function.
This is far more secure than a plaintext file in Git but less secure than a human-held key.

```bash
# Replace 'YOUR_UNSEAL_KEY' with the key from Step 1
kubectl create secret generic vault-unseal-keys -n vault \
  --from-literal=key1='YOUR_UNSEAL_KEY'
```

#### 3. (GitOps) Deploy the Auto-Unseal CronJob
This `CronJob` should be committed to the Git repository and managed by ArgoCD. It runs every minute,
checks if Vault is sealed, and if so, uses the key from the `Secret` to unseal it.
The `vault operator unseal` command is idempotent; it does nothing if Vault is already unsealed,
making this workflow robust.


### Configure Vault (The Auth Backbone)
These one-time actions are performed using the Initial Root Token saved from earlier.

#### 1. Exec into the Vault Pod and Login
```bash
kubectl exec -it vault-server-0 -n vault -- /bin/sh
export VAULT_ADDR="http://127.0.0.1:8200"
vault login YOUR_ROOT_TOKEN
```

### 2. Enable and Configure Kubernetes Auth Method
This method allows Kubernetes Service Accounts to authenticate to Vault using their own tokens.
```bash
# Enable the K8s auth method
vault auth enable kubernetes
Success! Enabled kubernetes auth method at: kubernetes/ [41]

# Configure it to talk to the K3s API server
# This uses the in-cluster service discovery
vault write auth/kubernetes/config \
       kubernetes_host="https://kubernetes.default.svc.cluster.local"
Success! Data written to: auth/kubernetes/config [42, 43]
```

### 3. Create a Vault Policy for VSO
This policy grants the VSO only the permission to read secrets from a specific path.
All homelab secrets will be stored under `secret/data/homelab/*` for organization.
```bash
vault policy write vso-policy - <<EOF
path "secret/data/homelab/*" {
  capabilities = ["read"]
}
EOF
Success! Uploaded policy: vso-policy [44]
```

### 4. Create a Vault Role for VSO
This "role" binds the `vso-policy` to the specific Kubernetes Service Account that the VSO will use.
We will name this service account `vso-service-account` and deploy it in the `vault-secrets-operator` namespace.
```bash
vault write auth/kubernetes/role/vso-role \
       bound_service_account_names=vso-service-account \
       bound_service_account_namespaces=vault-secrets-operator \
       policies=vso-policy \
       ttl=24h
Success! Data written to: auth/kubernetes/role/vso-role [47]
```

### 5. Create a Test Secret
A test secret for the `ollama` application will be created to verify the workflow.
```bash
# Enable the kv-v2 secrets engine at 'secret/' if not already
vault secrets enable -path=secret kv-v2

# Create a test secret
vault kv put secret/homelab/ollama api_key="my-super-secret-ollama-key"
Success! Data written to: secret/data/homelab/ollama [45]
```

### 6. Deploy the Vault Secrets Operator (VSO) via ArgoCD
Continue reading the documentation for setting up VSO in
the `vault-secrets-operator` directory in this repo.

