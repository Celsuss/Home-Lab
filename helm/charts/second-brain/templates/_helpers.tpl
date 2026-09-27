{{/*
Expand the name of the chart.
*/}}
{{- define "second-brain.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name. Named from .Values.name rather than the release so
resource names stay stable no matter what ArgoCD calls the release.
*/}}
{{- define "second-brain.fullname" -}}
{{- default .Values.name .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Chart name and version as used by the chart label.
*/}}
{{- define "second-brain.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "second-brain.labels" -}}
helm.sh/chart: {{ include "second-brain.chart" . }}
{{ include "second-brain.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "second-brain.selectorLabels" -}}
app.kubernetes.io/name: {{ include "second-brain.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
The sync pod spec, shared by the CronJob and the PostSync bootstrap Job so the
two cannot drift. Callers pass the root context.

`app: <fullname>` on the pod template is what the NetworkPolicy selects on.
*/}}
{{- define "second-brain.syncPodSpec" -}}
metadata:
  labels:
    {{- include "second-brain.selectorLabels" . | nindent 4 }}
    app: {{ include "second-brain.fullname" . }}
spec:
  restartPolicy: Never
  # Nothing here talks to the Kubernetes API.
  automountServiceAccountToken: false
  containers:
    - name: sync
      image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
      imagePullPolicy: {{ .Values.image.pullPolicy }}
      # git is not in the python image. Installing it here rather than baking
      # an image keeps this chart to plain upstream images; the script itself
      # has no dependencies to resolve, which is the failure mode that matters
      # (helm/charts/mcpo/README.md).
      command:
        - /bin/sh
        - -c
        - |
          set -eu
          apk add --no-cache git >/dev/null
          exec python3 /scripts/sync.py
      env:
        - name: OPEN_WEBUI_URL
          value: {{ .Values.openWebui.url | quote }}
        - name: OPEN_WEBUI_API_KEY
          valueFrom:
            secretKeyRef:
              name: {{ .Values.openWebui.apiKeySecret }}
              key: {{ .Values.openWebui.apiKeySecretKey }}
        - name: KB_NAME
          value: {{ .Values.knowledge.name | quote }}
        - name: KB_DESCRIPTION
          value: {{ .Values.knowledge.description | quote }}
        - name: REPO_DIR
          value: /repo
        - name: NOTES_SUBDIR
          value: {{ .Values.git.notesSubdir | quote }}
        - name: GIT_URL
          value: {{ .Values.git.url | quote }}
        - name: GIT_BRANCH
          value: {{ .Values.git.branch | quote }}
        - name: GIT_USERNAME
          valueFrom:
            secretKeyRef:
              name: {{ .Values.vault.secretName }}
              key: {{ .Values.vault.usernameKey }}
        - name: GIT_TOKEN
          valueFrom:
            secretKeyRef:
              name: {{ .Values.vault.secretName }}
              key: {{ .Values.vault.tokenKey }}
      resources:
        {{- toYaml .Values.resources | nindent 8 }}
      volumeMounts:
        - name: repo
          mountPath: /repo
        - name: scripts
          mountPath: /scripts
          readOnly: true
  volumes:
    # emptyDir, deliberately not a PVC. Nothing needs to survive between runs -
    # the state lives in Open WebUI's database - and a `--depth 1` clone of the
    # notes repo is 19 MB from a Service in this same cluster.
    #
    # A PVC here was actively harmful: `local-path` is WaitForFirstConsumer, so
    # the claim only binds once a pod mounting it is scheduled, but the only
    # pods that mount it are the PostSync hook (which ArgoCD will not start
    # until the Sync phase is healthy) and the CronJob. ArgoCD therefore parked
    # on "waiting for healthy state of .../second-brain-pvc" until the CronJob
    # happened to fire. It also let the PostSync Job and a scheduled run write
    # the same RWO clone at once, which `concurrencyPolicy: Forbid` does not
    # guard against.
    - name: repo
      emptyDir:
        sizeLimit: 1Gi
    - name: scripts
      configMap:
        name: {{ include "second-brain.fullname" . }}-sync
{{- end }}
