{{/*
Expand the name of the chart.
*/}}
{{- define "open-terminal.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name. Resources are named from .Values.name so the Service
DNS record stays stable (`open-terminal.ai-workloads.svc.cluster.local`) no
matter what ArgoCD calls the release - the Open WebUI connection points at it.
*/}}
{{- define "open-terminal.fullname" -}}
{{- default .Values.name .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Chart name and version as used by the chart label.
*/}}
{{- define "open-terminal.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "open-terminal.labels" -}}
helm.sh/chart: {{ include "open-terminal.chart" . }}
{{ include "open-terminal.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "open-terminal.selectorLabels" -}}
app.kubernetes.io/name: {{ include "open-terminal.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
In-cluster URL of the terminal, as Open WebUI's backend reaches it.
*/}}
{{- define "open-terminal.serviceUrl" -}}
{{- printf "http://%s.%s.svc.cluster.local:%v" (include "open-terminal.fullname" .) .Values.namespace .Values.service.port }}
{{- end }}
