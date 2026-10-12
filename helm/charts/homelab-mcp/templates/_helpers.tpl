{{/*
Expand the name of the chart.
*/}}
{{- define "homelab-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name. Named from .Values.name rather than the release so
resource names stay stable no matter what ArgoCD calls the release.
*/}}
{{- define "homelab-mcp.fullname" -}}
{{- default .Values.name .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Chart name and version as used by the chart label.
*/}}
{{- define "homelab-mcp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "homelab-mcp.labels" -}}
helm.sh/chart: {{ include "homelab-mcp.chart" . }}
{{ include "homelab-mcp.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "homelab-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "homelab-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
