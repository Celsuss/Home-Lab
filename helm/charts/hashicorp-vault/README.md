# Hashicorp vault helm chart

## Create a secret

### Create secret in hashicorp vault
To create a secret you first need to connect to the pod and create a secret using bash.
``` bash
# 1. ssh in to container
kubectl exec -it vault-server-0 -n vault -- /bin/sh

# 2. login to vault
vault login <YOUR_ROOT_TOKEN>

# 2. Write the secret data
# Syntax: vault kv put <mount>/<path> <key>=<value>
vault kv put secret/homelab/homepage-db password="super-secure-password-123" username="db-user"
```

### Get secret
To get a secret run the following command inside the container.
``` bash
vault kv get secret/homelab/tandoor-recipes
```

### Create a VaultStaticSecret
Create and deploy a `VaultStaticSecret` in kubernetes.
``` bash
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultStaticSecret
metadata:
  name: homepage-db-secret-sync
  namespace: default  # The namespace where your APP runs
spec:
  # Reference the VSO auth method (Global or Local)
  vaultAuthRef: default

  # Where did you put it in Vault?
  mount: secret
  type: kv-v2
  path: homelab/homepage-db # Matches Step 1

  # How often to check Vault for updates (e.g., if you rotate the password)
  refreshAfter: 60s

  # What should the Kubernetes Secret look like?
  destination:
    create: true
    name: homepage-db-creds  # The final K8s Secret name
    overwrite: true
    # Optional: Transformation (if you want to rename keys)
    # transformation:
    #   excludeRaw: true
```

### Consume it in your Application
Now that everything is deployed lets consume the secret.
``` bash
apiVersion: apps/v1
kind: Deployment
metadata:
  name: homepage
  namespace: default
spec:
  template:
    spec:
      containers:
        - name: web
          image: my-app:latest
          env:
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: homepage-db-creds  # Matches 'destination.name' from Step 2
                  key: password            # Matches the key you wrote in Step 1
```


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
Each namespace that uses a `VaultStaticSecret` needs a `vso-service-account` ServiceAccount.
Using `"*"` for namespaces allows any namespace with this SA to authenticate — the policy still
controls which Vault paths are readable.
```bash
vault write auth/kubernetes/role/vso-role \
       bound_service_account_names=vso-service-account \
       bound_service_account_namespaces="*" \
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

