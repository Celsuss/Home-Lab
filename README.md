# Home-Lab
Home lab setup

## Deployment
Go to `/scripts/` and run `/deploy-argo-cd.sh`.
ArgoCD will then take care of deploying everything.

## Access services
1. Get Node ip from running `kubectl get nodes -o wide`
2. Add `NODE-IP SERVICE-NAME.homelab.local` to `/etc/hosts`.

## Setup
1. Install K3s.
```bash
yay -S k3s-bin
```
2. Install nvidia-container-toolkit
```bash
yay -S nvidia-container-toolkit
```
3. Configure containerd to use nvidia
```bash
sudo cp /var/lib/rancher/k3s/agent/etc/containerd/config.toml /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl    # First take a copy of current config.toml
sudo nvidia-ctk runtime configure --runtime=containerd --config=/var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl  # Add nvidia config
```
4. Setup Kubernetes Nvidia Device Plugin with special config for K3s.
```bash
kubectl apply -f - <<'EOF'
# Copyright (c) 2019, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: nvidia-device-plugin-daemonset
  namespace: kube-system
spec:
  selector:
    matchLabels:
      name: nvidia-device-plugin-ds
  updateStrategy:
    rollingUpdate:
      maxSurge: 0
      maxUnavailable: 1
    type: RollingUpdate
  template:
    metadata:
      labels:
        name: nvidia-device-plugin-ds
    spec:
      tolerations:
      # This toleration is deprecated. Kept for backward compatibility
      # See https://kubernetes.io/docs/concepts/configuration/taint-and-toleration/
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
      # Mark this pod as a critical add-on; when enabled, the critical add-on
      # scheduler reserves resources for critical add-on pods so that they can
      # be rescheduled after a failure.
      # See https://kubernetes.io/docs/tasks/administer-cluster/guaranteed-scheduling-critical-addon-pods/
      priorityClassName: "system-node-critical"
      runtimeClassName: nvidia
      containers:
      - env:
        - name: FAIL_ON_INIT_ERROR
          value: "false"
        image: nvcr.io/nvidia/k8s-device-plugin:v0.17.1
        name: nvidia-device-plugin-ctr
        securityContext:
          allowPrivilegeEscalation: false
          capabilities:
            drop:
            - ALL
        volumeMounts:
        - name: device-plugin
          mountPath: /var/lib/kubelet/device-plugins
      volumes:
      - name: device-plugin
        hostPath:
          path: /var/lib/kubelet/device-plugins
EOF
```
5. Install tailscale operator
```bash
helm repo add tailscale https://pkgs.tailscale.com/helmcharts
helm repo update
helm upgrade --install tailscale-operator tailscale/tailscale-operator \
  --namespace tailscale \
  --create-namespace \
  --set-string oauth.clientId="<Your-Client-ID>" \
  --set-string oauth.clientSecret="<Your-Client-Secret>" \
  --wait
```

## Create secrets

### Encrypt secrets
1. Make sure you have added `.sops.yaml` to the root of the repo with the public keys.
2. Encrypt secrets by running `sops -e -i values-secrets.yaml`.
3. Make sure you have added the private key to the argo-cd chart.
