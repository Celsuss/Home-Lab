# templates/_helpers.tpl - Reusable template helpers for consistent naming and labeling
{{/*
Expand the name of the chart. This creates a standard name that can be used
throughout your Kubernetes resources. It uses the chart name by default,
but allows override via the nameOverride value.
*/}}
{{- define "ollama.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name. This combines the release name
with the chart name to create unique resource names. This is important
when you have multiple Helm releases of the same chart in a cluster.
We truncate at 63 chars because some Kubernetes name fields are limited to this.
*/}}
{{- define "ollama.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
This is used in labels to identify which chart version created the resource.
*/}}
{{- define "ollama.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to all resources. These labels help with resource
management, monitoring, and debugging. Kubernetes best practices recommend
including these standard labels on all resources.
*/}}
{{- define "ollama.labels" -}}
helm.sh/chart: {{ include "ollama.chart" . }}
{{ include "ollama.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels are used to identify which pods belong to this deployment.
These labels must be stable across upgrades, so they don't include
version information that might change.
*/}}
{{- define "ollama.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ollama.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use. This allows you to
either create a new service account or use an existing one.
The service account is important for RBAC (role-based access control).
*/}}
{{- define "ollama.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "ollama.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create a default image tag. This allows the image tag to be overridden
in values.yaml, but falls back to the Chart.AppVersion if not specified.
This is a common pattern in Helm charts.
*/}}
{{- define "ollama.imageTag" -}}
{{- .Values.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Helper function to extract non-GPU resources from a resource block.
This is useful when we need to apply GPU resources separately.
*/}}
{{- define "ollama.resourcesWithoutGpu" -}}
{{- range $key, $value := . }}
{{- if not (hasPrefix "nvidia.com/" $key) }}
{{ $key }}: {{ $value }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Generate the model download script for the init container.
This template creates a bash script that downloads all specified models
declaratively, ensuring they're available when Ollama starts.
*/}}
{{- define "ollama.modelDownloadScript" -}}
#!/bin/bash
set -euo pipefail

echo "=== Ollama Model Download Process Starting ==="
echo "Models to download: {{ join ", " .Values.models.list }}"

# Start Ollama server in background for model downloads
echo "Starting temporary Ollama server for model downloads..."
ollama serve &
SERVER_PID=$!

# Function to cleanup on exit
cleanup() {
    echo "Cleaning up temporary Ollama server..."
    kill $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true
}
trap cleanup EXIT

# Wait for Ollama server to be ready with proper timeout
echo "Waiting for Ollama server to become ready..."
TIMEOUT=60
COUNTER=0
while [ $COUNTER -lt $TIMEOUT ]; do
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo "✓ Ollama server is ready!"
        break
    fi

    if [ $COUNTER -eq $((TIMEOUT - 1)) ]; then
        echo "✗ Timeout waiting for Ollama server to start"
        exit 1
    fi

    sleep 1
    COUNTER=$((COUNTER + 1))
done

# Download each model with progress indication
TOTAL_MODELS={{ len .Values.models.list }}
CURRENT_MODEL=0

{{- range .Values.models.list }}
CURRENT_MODEL=$((CURRENT_MODEL + 1))
echo ""
echo "=== Downloading model $CURRENT_MODEL/$TOTAL_MODELS: {{ . }} ==="

# Check if model already exists
if ollama list | grep -q "^{{ . }}"; then
    echo "✓ Model {{ . }} already exists, skipping download"
else
    echo "Downloading {{ . }}..."
    if ollama pull "{{ . }}"; then
        echo "✓ Successfully downloaded: {{ . }}"
    else
        echo "✗ Failed to download: {{ . }}"
        exit 1
    fi
fi
{{- end }}

echo ""
echo "=== Model Download Process Completed Successfully ==="
echo "All {{ len .Values.models.list }} models are now available"

# List all available models for verification
echo ""
echo "Available models:"
ollama list
{{- end }}

{{/*
Generate the full image name including repository and tag.
This centralizes image name logic and makes it easy to change
image sources or versions consistently.
*/}}
{{- define "ollama.image" -}}
{{- printf "%s:%s" .Values.image.repository (include "ollama.imageTag" .) }}
{{- end }}
