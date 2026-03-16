# k8s-gateway

In-cluster DNS server for resolving `*.homelab.local` services. Runs as a LoadBalancer service that responds to DNS queries for hostnames defined by ingress resources.

## How it works

1. k8s-gateway watches ingress resources in the cluster
2. It serves DNS responses mapping hostnames (e.g., `glance.homelab.local`) to the Traefik LoadBalancer IP
3. systemd-resolved on the host is configured to route `homelab.local` queries to k8s-gateway via `/etc/systemd/resolved.conf.d/homelab.conf`

## Troubleshooting: DNS resolution not working

If `*.homelab.local` services stop resolving (e.g., after a reboot or IP change), follow these steps.

### 1. Check if the cluster is running

```bash
kubectl get nodes
```

If this fails, the cluster is down — DNS won't work until it's back up.

### 2. Check if k8s-gateway is running

```bash
kubectl get pods -n k8s-gateway
kubectl get svc -n k8s-gateway
```

Note the `EXTERNAL-IP` on the service — this is the IP k8s-gateway is listening on.

### 3. Test DNS resolution directly

Query k8s-gateway directly to confirm it can resolve names:

```bash
dig @<EXTERNAL-IP> glance.homelab.local +short
```

If this returns an IP, k8s-gateway is working. If not, check pod logs:

```bash
kubectl logs -n k8s-gateway -l app.kubernetes.io/name=k8s-gateway
```

### 4. Check systemd-resolved routing

```bash
cat /etc/systemd/resolved.conf.d/homelab.conf
resolvectl status
```

The `DNS=` value in `homelab.conf` must point to an IP where k8s-gateway is reachable.

### 5. Common fix: DNS IP mismatch after reboot

**Symptom:** `dig @127.0.0.1 glance.homelab.local` works, but `nslookup glance.homelab.local` fails.

**Cause:** The host IP changed (e.g., DHCP assigned a different address), but `homelab.conf` still points to the old IP.

**Fix:** Set the DNS server to `127.0.0.1` so it always resolves locally regardless of IP changes:

```bash
sudo sed -i 's/DNS=.*/DNS=127.0.0.1/' /etc/systemd/resolved.conf.d/homelab.conf
sudo systemctl restart systemd-resolved
```

This works because the k8s-gateway LoadBalancer binds to all interfaces, including loopback.

### 6. Verify the fix

```bash
nslookup glance.homelab.local
curl -k https://glance.homelab.local
```
