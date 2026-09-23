{{/*
Expand the name of the chart.
*/}}
{{- define "cptr.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name. Resources are named from .Values.name so the Service
DNS record stays stable (`cptr.ai-workloads.svc.cluster.local`) no matter what
ArgoCD calls the release - the tailnet hostname and the Open WebUI connection
both point at it.
*/}}
{{- define "cptr.fullname" -}}
{{- default .Values.name .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Chart name and version as used by the chart label.
*/}}
{{- define "cptr.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "cptr.labels" -}}
helm.sh/chart: {{ include "cptr.chart" . }}
{{ include "cptr.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "cptr.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cptr.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
In-cluster URL of cptr, as Open WebUI's backend reaches it (Phase 2).
*/}}
{{- define "cptr.serviceUrl" -}}
{{- printf "http://%s.%s.svc.cluster.local:%v" (include "cptr.fullname" .) .Values.namespace .Values.service.port }}
{{- end }}
