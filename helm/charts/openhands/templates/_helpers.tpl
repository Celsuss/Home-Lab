{{/*
Expand the name of the chart.
*/}}
{{- define "openhands.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name. Resources are named from .Values.name so the Service
DNS record stays stable (`openhands.ai-workloads.svc.cluster.local`) no matter
what ArgoCD calls the release - the tailnet hostname points at it too.
*/}}
{{- define "openhands.fullname" -}}
{{- default .Values.name .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Chart name and version as used by the chart label.
*/}}
{{- define "openhands.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "openhands.labels" -}}
helm.sh/chart: {{ include "openhands.chart" . }}
{{ include "openhands.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "openhands.selectorLabels" -}}
app.kubernetes.io/name: {{ include "openhands.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
In-cluster URL of the unified entry point.
*/}}
{{- define "openhands.serviceUrl" -}}
{{- printf "http://%s.%s.svc.cluster.local:%v" (include "openhands.fullname" .) .Values.namespace .Values.service.port }}
{{- end }}
