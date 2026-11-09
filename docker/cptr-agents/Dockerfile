# cptr-agents: Open WebUI Computer plus the tooling a coding agent expects.
#
# The upstream image ships Python 3.12, uv, git and gh only - no curl, no Node,
# no compiler - so cptr's Admin -> Agents profiles report "Not found" and an
# agent can't do much beyond editing files. This layer adds the Claude Code
# CLI and a general toolbox, then drops back to the unprivileged `cptr` user.
# See docs/plans/2026-11-09-claude-code-agents.md (D2).
#
# Everything downloaded is pinned by version AND sha256. To bump a tool, change
# its version ARG, then recompute the checksum:
#   curl -fsSL <url> | sha256sum
# Helm and Node publish their own checksums (.sha256sum / SHASUMS256.txt);
# Claude Code's is in https://downloads.claude.ai/claude-code-releases/<ver>/manifest.json
# under platforms.linux-x64.checksum.
#
# Only linux/amd64 is pinned - the cluster is a single x86_64 node.
ARG CPTR_VERSION=0.9.21
FROM ghcr.io/open-webui/computer:${CPTR_VERSION}

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# --- Debian packages ---------------------------------------------------------
# Network/data:   curl wget ca-certificates jq dnsutils netcat-openbsd rsync
# Search/inspect: ripgrep fd-find tree file less procps sqlite3
# Archives:       unzip zip xz-utils zstd
# Build:          build-essential (gcc, make) - native Python/Node deps
# Lint:           shellcheck
# Editors/ssh:    nano vim-tiny openssh-client (git commit, git over ssh)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl dnsutils fd-find file jq less \
      nano netcat-openbsd openssh-client procps ripgrep rsync shellcheck \
      sqlite3 tree unzip vim-tiny wget xz-utils zip zstd && \
    ln -s /usr/bin/fdfind /usr/local/bin/fd && \
    rm -rf /var/lib/apt/lists/*

# --- Node.js (LTS) -----------------------------------------------------------
# For JS projects, `npx` MCP servers and repomix. Bookworm's own nodejs is 18,
# too old for most current tooling, so this is the official tarball.
ARG NODE_VERSION=26.13.0
ARG NODE_SHA256=d28a96af6c38596f6d9d97c0ee531c13d238d757742387d1928de822d959e997
RUN curl -fsSL -o /tmp/node.tar.xz \
      "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" && \
    echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum -c - && \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
      --exclude='*/CHANGELOG.md' --exclude='*/README.md' --exclude='*/LICENSE' && \
    rm /tmp/node.tar.xz

# --- Homelab repo tooling ----------------------------------------------------
# What `just check` and the Woodpecker pr-checks need, so an agent can validate
# a Home-Lab change before pushing it. No kubectl on purpose: this pod has no
# cluster credentials (README.md, Containment).
ARG HELM_VERSION=4.3.1
ARG HELM_SHA256=0403a88ae20913d11b10a2467b50087721fea7581736da6b9d3992f5357fe54b
ARG KUBECONFORM_VERSION=0.8.0
ARG KUBECONFORM_SHA256=9bc2bffbf71f261128533edaf912153948b7ff238f9a531ae6d34466ec287883
ARG YQ_VERSION=4.54.3
ARG YQ_SHA256=129534601871538efe0ba4c5e62a34fb1d5f469bcb975c4fddeb467d82974973
ARG JUST_VERSION=1.59.0
ARG JUST_SHA256=409044617b6f06517c1035e55ca38c8c856ff8b650e41bc2aa1ef82d5903a23e
ARG YAMLFMT_VERSION=0.21.0
ARG YAMLFMT_SHA256=1f300d9257b232bb3b541d7fb1b0e6b3c121bcbab381c86cd38cb8722be8a566
RUN cd /tmp && \
    curl -fsSL -o helm.tgz "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz" && \
    echo "${HELM_SHA256}  helm.tgz" | sha256sum -c - && \
    tar -xzf helm.tgz --strip-components=1 -C /usr/local/bin linux-amd64/helm && \
    curl -fsSL -o kubeconform.tgz \
      "https://github.com/yannh/kubeconform/releases/download/v${KUBECONFORM_VERSION}/kubeconform-linux-amd64.tar.gz" && \
    echo "${KUBECONFORM_SHA256}  kubeconform.tgz" | sha256sum -c - && \
    tar -xzf kubeconform.tgz -C /usr/local/bin kubeconform && \
    curl -fsSL -o /usr/local/bin/yq \
      "https://github.com/mikefarah/yq/releases/download/v${YQ_VERSION}/yq_linux_amd64" && \
    echo "${YQ_SHA256}  /usr/local/bin/yq" | sha256sum -c - && \
    chmod 755 /usr/local/bin/yq && \
    curl -fsSL -o just.tgz \
      "https://github.com/casey/just/releases/download/${JUST_VERSION}/just-${JUST_VERSION}-x86_64-unknown-linux-musl.tar.gz" && \
    echo "${JUST_SHA256}  just.tgz" | sha256sum -c - && \
    tar -xzf just.tgz -C /usr/local/bin just && \
    curl -fsSL -o yamlfmt.tgz \
      "https://github.com/google/yamlfmt/releases/download/v${YAMLFMT_VERSION}/yamlfmt_${YAMLFMT_VERSION}_Linux_x86_64.tar.gz" && \
    echo "${YAMLFMT_SHA256}  yamlfmt.tgz" | sha256sum -c - && \
    tar -xzf yamlfmt.tgz -C /usr/local/bin yamlfmt && \
    rm -f /tmp/*.tgz

# --- Claude Code -------------------------------------------------------------
# The native binary, installed system-wide so the PVC mounted at $HOME can
# never shadow it. The auto-updater is off: it would rewrite the binary behind
# git's back, and /usr/local is not writable by `cptr` anyway. Bump CLAUDE_VERSION
# (and its checksum) in a PR instead.
ARG CLAUDE_VERSION=2.1.311
ARG CLAUDE_SHA256=86dc1fcc69498159eaf15f446613e847010f9036bfbbdffd4c49350be8489ada
RUN curl -fsSL -o /usr/local/bin/claude \
      "https://downloads.claude.ai/claude-code-releases/${CLAUDE_VERSION}/linux-x64/claude" && \
    echo "${CLAUDE_SHA256}  /usr/local/bin/claude" | sha256sum -c - && \
    chmod 755 /usr/local/bin/claude

# `npm i -g` and `uv tool install` land on the PVC ($HOME=/workspace in the
# chart), so tools the agent adds itself survive a restart.
ENV DISABLE_AUTOUPDATER=1 \
    NPM_CONFIG_PREFIX=/workspace/.npm-global \
    PATH="/workspace/.npm-global/bin:/workspace/.local/bin:${PATH}"

USER cptr
