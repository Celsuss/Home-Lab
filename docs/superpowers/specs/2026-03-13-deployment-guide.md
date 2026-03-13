# cert-manager + TLS + DNS — Deployment Guide

After merging `feat/cert-manager-tls-dns` and pushing to main, ArgoCD will begin syncing the new charts. Follow these steps in order.

---

## Step 1: Wait for k8s-gateway and cert-manager to sync

ArgoCD will auto-sync both new charts. cert-manager has `sync-wave: -1` so it deploys first.

```bash
# Watch ArgoCD sync status
kubectl get applications -n argo-cd -w

# Wait for cert-manager pods to be ready (3 pods: controller, webhook, cainjector)
kubectl get pods -n cert-manager -w

# Wait for k8s-gateway pod to be ready
kubectl get pods -n k8s-gateway -w
```

**Expected:** All three cert-manager pods and the k8s-gateway pod show `Running` / `Ready`.

**Troubleshooting:**
- If cert-manager CRDs fail to install, manually sync: `argocd app sync cert-manager`
- If k8s-gateway fails, check the chart version: `helm search repo k8s-gateway`

---

## Step 2: Validate cert-manager ClusterIssuers

```bash
kubectl get clusterissuer
```

**Expected output:**
```
NAME                READY   AGE
selfsigned-issuer   True    ...
homelab-ca          True    ...
```

If `homelab-ca` shows `False`, check the CA certificate:
```bash
kubectl get certificate homelab-ca -n cert-manager
kubectl describe certificate homelab-ca -n cert-manager
```

---

## Step 3: Extract and trust the CA certificate

Extract the CA cert from the cluster:

```bash
kubectl get secret homelab-ca-tls -n cert-manager \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > /tmp/homelab-ca.crt
```

Verify it looks correct:

```bash
openssl x509 -in /tmp/homelab-ca.crt -noout -subject -issuer -dates
```

**Expected:** Subject and Issuer both show `CN = homelab-ca`, with a 10-year validity.

Install on your Arch Linux machine:

```bash
sudo trust anchor /tmp/homelab-ca.crt
```

Verify it's trusted:

```bash
trust list | grep -A2 "homelab-ca"
```

For other machines:
- **macOS:** `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain /tmp/homelab-ca.crt`
- **Windows:** Import into "Trusted Root Certification Authorities" via `certmgr.msc`
- **Firefox** (all platforms): Firefox uses its own cert store. Go to Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import → select `homelab-ca.crt`

---

## Step 4: Configure CoreDNS stub zone for in-cluster DNS

Get the k8s-gateway service ClusterIP:

```bash
K8S_GATEWAY_IP=$(kubectl get svc -n k8s-gateway k8s-gateway -o jsonpath='{.spec.clusterIP}')
echo "k8s-gateway ClusterIP: $K8S_GATEWAY_IP"
```

Create the CoreDNS custom ConfigMap:

```bash
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns-custom
  namespace: kube-system
data:
  homelab.server: |
    homelab.local:53 {
        errors
        cache 30
        forward . ${K8S_GATEWAY_IP}
    }
EOF
```

Restart CoreDNS to pick up the new config:

```bash
kubectl rollout restart deployment coredns -n kube-system
kubectl rollout status deployment coredns -n kube-system
```

Validate DNS resolution from inside the cluster:

```bash
# Test auto-discovered service (standard Ingress)
kubectl run -it --rm dns-test --image=busybox:1.36 --restart=Never -- \
  nslookup glance.homelab.local

# Test static entry (Kanidm uses IngressRouteTCP)
kubectl run -it --rm dns-test2 --image=busybox:1.36 --restart=Never -- \
  nslookup kanidm.homelab.local
```

**Expected:** Both return an IP address (the Traefik ingress IP).

**Troubleshooting:**
- If DNS doesn't resolve, check CoreDNS logs: `kubectl logs -n kube-system -l k8s-app=kube-dns`
- If CoreDNS shows errors forwarding to k8s-gateway, verify the k8s-gateway pod is running and the ClusterIP is correct
- K3s may overwrite the CoreDNS ConfigMap on upgrades. If DNS stops working after a K3s upgrade, re-apply this ConfigMap

---

## Step 5: Configure client machine DNS

### Option A: systemd-resolved (recommended for Arch Linux)

Create a drop-in config:

```bash
sudo mkdir -p /etc/systemd/resolved.conf.d
sudo tee /etc/systemd/resolved.conf.d/homelab.conf <<EOF
[Resolve]
DNS=192.168.1.50
Domains=~homelab.local
EOF
```

This tells systemd-resolved to send queries for `*.homelab.local` to your K3s server node (192.168.1.50), while all other DNS queries go through your normal resolver.

Restart the resolver:

```bash
sudo systemctl restart systemd-resolved
```

Verify:

```bash
resolvectl status | grep -A5 "homelab"
```

### Option B: NetworkManager (if not using systemd-resolved)

```bash
# Find your active connection name
nmcli connection show --active

# Add the K3s node as a DNS server for the homelab.local domain
nmcli connection modify "YOUR_CONNECTION" ipv4.dns "192.168.1.50"
nmcli connection modify "YOUR_CONNECTION" ipv4.dns-search "homelab.local"
nmcli connection up "YOUR_CONNECTION"
```

### Remove old /etc/hosts entries

```bash
# Show current homelab entries
grep 'homelab.local' /etc/hosts

# Remove them (backup first)
sudo cp /etc/hosts /etc/hosts.bak
sudo sed -i '/homelab\.local/d' /etc/hosts
```

### Validate from your machine

```bash
# DNS resolution
dig glance.homelab.local +short
dig kanidm.homelab.local +short
dig argocd.homelab.local +short

# All should return the Traefik ingress IP
```

---

## Step 6: Verify Traefik websecure entrypoint

K3s Traefik should have the websecure entrypoint (port 443) enabled by default. Verify:

```bash
# Check Traefik is listening on 443
kubectl get svc traefik -n kube-system -o jsonpath='{.spec.ports[*].port}'

# Should include 443. If not, check Traefik args:
kubectl get deployment traefik -n kube-system \
  -o jsonpath='{.spec.template.spec.containers[0].args}' | tr ',' '\n'
```

**Expected:** Port 443 is listed and Traefik args include `--entryPoints.websecure.address=:443`.

---

## Step 7: Validate Batch 1 (Kanidm + ArgoCD)

### Kanidm

Check the certificate was issued:

```bash
kubectl get certificate -n kanidm
```

**Expected:** `kanidm-tls` shows `READY: True`.

If not ready, debug:

```bash
kubectl describe certificate kanidm-tls -n kanidm
kubectl get certificaterequest -n kanidm
kubectl describe certificaterequest -n kanidm -l app.kubernetes.io/name=kanidm
```

Verify Kanidm is accessible:

```bash
# Should succeed without -k if CA is trusted (Step 3)
curl -v https://kanidm.homelab.local 2>&1 | grep -E "subject:|issuer:|SSL"
```

**Expected:** `issuer: CN=homelab-ca` in the output.

### ArgoCD

Check the certificate:

```bash
kubectl get certificate -n argo-cd
```

Verify HTTPS access:

```bash
curl -v https://argocd.homelab.local 2>&1 | grep -E "subject:|issuer:|SSL"
```

**Test OIDC login:**

1. Open `https://argocd.homelab.local` in your browser
2. Click "Login via Kanidm"
3. Complete the OIDC flow

**Expected:** Login succeeds without any TLS errors or DNS errors.

**Troubleshooting:**
- If OIDC fails with "connection refused" or DNS error, check that the ArgoCD server pod can resolve `kanidm.homelab.local` via the CoreDNS stub zone (Step 4)
- If OIDC fails with TLS errors, verify the ArgoCD pod trusts the homelab CA. The `oidc.tls.insecure.skip.verify` was removed — if Kanidm's cert is not yet issued, OIDC will fail. Check `kubectl get certificate -n kanidm` first
- Re-add `oidc.tls.insecure.skip.verify: "true"` temporarily if needed to unblock while debugging

---

## Step 8: Validate Batch 2 (all remaining services)

Check all certificates at once:

```bash
kubectl get certificates --all-namespaces
```

**Expected:** All certificates show `READY: True`.

Spot-check a few services:

```bash
curl -s -o /dev/null -w "%{http_code} %{ssl_verify_result}\n" https://glance.homelab.local
curl -s -o /dev/null -w "%{http_code} %{ssl_verify_result}\n" https://vault.homelab.local
curl -s -o /dev/null -w "%{http_code} %{ssl_verify_result}\n" https://khoj.homelab.local
curl -s -o /dev/null -w "%{http_code} %{ssl_verify_result}\n" https://beszel.homelab.local
curl -s -o /dev/null -w "%{http_code} %{ssl_verify_result}\n" https://uptime-kuma.homelab.local
```

**Expected:** HTTP status 200 (or 302 for apps with login pages) and `ssl_verify_result` of `0` (meaning the cert is valid and trusted).

Open each service in your browser and verify the lock icon shows a valid certificate:

| Service | URL |
|---------|-----|
| Glance | https://glance.homelab.local |
| Vault | https://vault.homelab.local |
| Khoj | https://khoj.homelab.local |
| Beszel | https://beszel.homelab.local |
| Uptime Kuma | https://uptime-kuma.homelab.local |
| Audiobookshelf | https://audiobookshelf.homelab.local |
| Ezbookkeeping | https://ezbookkeeping.homelab.local |
| Donetick | https://donetick.homelab.local |
| Tandoor Recipes | https://tandoor.homelab.local |
| Karakeep | https://karakeep.homelab.local |
| Kanidm | https://kanidm.homelab.local |
| ArgoCD | https://argocd.homelab.local |

---

## Rollback

If something goes wrong and you need to revert:

```bash
# Revert the branch on GitHub (or reset locally)
git revert --no-commit HEAD~15..HEAD
git commit -m "revert: undo cert-manager/TLS/DNS changes"
git push

# ArgoCD will auto-sync and revert all changes
# Re-add /etc/hosts entries if needed
# Re-add the CoreDNS custom ConfigMap deletion:
kubectl delete configmap coredns-custom -n kube-system
kubectl rollout restart deployment coredns -n kube-system
```

---

## Post-Deployment Notes

- **Certificate rotation:** cert-manager will automatically renew certificates before they expire (default 90-day certs, renewed at 2/3 lifetime). Kanidm requires a pod restart to pick up renewed certs — consider installing [Reloader](https://github.com/stakater/Reloader) in the future to automate this.
- **New charts:** When adding new services, add `cert-manager.io/cluster-issuer: homelab-ca` to the Ingress annotations and a `tls` block in values. cert-manager handles the rest.
- **K3s upgrades:** May overwrite the CoreDNS ConfigMap. Re-apply the `coredns-custom` ConfigMap from Step 4 after K3s upgrades.
- **Future Let's Encrypt:** When ready, register a real domain, add a DNS provider API token, create an ACME ClusterIssuer, and switch chart annotations. See `docs/superpowers/specs/2026-03-13-cert-manager-tls-dns-design.md` for details.
