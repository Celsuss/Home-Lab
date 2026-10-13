{{/*
Expand the name of the chart.
*/}}
{{- define "mcp-memory-service.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name. Named from .Values.name rather than the release so
resource names stay stable no matter what ArgoCD calls the release.
*/}}
{{- define "mcp-memory-service.fullname" -}}
{{- default .Values.name .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Chart name and version as used by the chart label.
*/}}
{{- define "mcp-memory-service.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mcp-memory-service.labels" -}}
helm.sh/chart: {{ include "mcp-memory-service.chart" . }}
{{ include "mcp-memory-service.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mcp-memory-service.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-memory-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
