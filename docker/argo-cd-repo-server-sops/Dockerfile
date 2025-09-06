# /docker/argo-cd-repo-server-sops

# Stage 1: Get the SOPS binary from its official Alpine-based image
# Pinning to a specific version like v3.10.2 ensures reproducible builds.
FROM ghcr.io/getsops/sops:v3.10.2-alpine as sops

FROM quay.io/argoproj/argocd:v3.1.4


# Copy the sops binary from the first stage into the final image's PATH
# This makes the 'sops' command available in the container.
COPY --from=sops /usr/local/bin/sops /usr/local/bin/sops
