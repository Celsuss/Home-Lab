# /docker/argo-cd-repo-server-sops

# Stage 1: Get the SOPS binary from its official Alpine-based image
# Pinning to a specific version like v3.10.2 ensures reproducible builds.
FROM ghcr.io/getsops/sops:v3.10.2-alpine as sops

# Stage 2: Use the official Argo CD image as our base
# The tag must match the version deployed by your Helm chart.
# For example, Argo CD Helm chart 6.11.0 uses Argo CD v2.12.2.
# Check your chart's documentation for the correct image tag.
FROM quay.io/argoproj/argocd:v2.12.2

# Copy the sops binary from the first stage into the final image's PATH
# This makes the 'sops' command available in the container.
COPY --from=sops /usr/local/bin/sops /usr/local/bin/sops
