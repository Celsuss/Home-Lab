ARG ARGOCD_VERSION="v3.1.4"
# docker/argo-cd-repo-server-sops/Dockerfile
FROM quay.io/argoproj/argocd:${ARGOCD_VERSION}

# Define tool versions for maintainability
ARG SOPS_VERSION="3.8.1"
ARG AGE_VERSION="1.1.1"
ARG HELM_SECRETS_VERSION="4.6.0"

# Switch to root user to install packages and binaries
USER root

# Install dependencies needed for downloading tools and for the helm plugin install command
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Download and install sops and age binaries directly
# Using dpkg to determine architecture makes the Dockerfile more portable
RUN export ARCH=$(dpkg --print-architecture) && \
    wget -qO /usr/local/bin/sops "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.${ARCH}" && \
    wget -qO- "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/age-v${AGE_VERSION}-linux-${ARCH}.tar.gz" | tar -xz -C /usr/local/bin/ --strip-components=1 age/age && \
    chmod +x /usr/local/bin/sops /usr/local/bin/age

# Switch back to the non-root argocd user
USER argocd

# Install the helm-secrets plugin. This now works because git is installed.
RUN helm plugin install https://github.com/jkroepke/helm-secrets --version ${HELM_SECRETS_VERSION}
