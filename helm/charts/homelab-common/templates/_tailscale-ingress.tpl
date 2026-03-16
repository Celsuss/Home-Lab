{{- define "homelab-common.tailscale-ingress" -}}
{{- if .Values.tailscale.enabled }}
{{- $svcName := .serviceName | default (.Values.tailscale.serviceName | default .fullname) }}
{{- $svcPort := .servicePort | default .Values.tailscale.servicePort }}
{{- if not $svcPort }}{{- $svcPort = .Values.service.port }}{{- end }}
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .fullname }}-tailscale-ingress
  namespace: {{ .namespace }}
  labels:
    {{- .labels | nindent 4 }}
spec:
  ingressClassName: tailscale
  tls:
    - hosts:
        - {{ .fullname | quote }}
  rules:
    - host: {{ .fullname | quote }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ $svcName }}
                port:
                  number: {{ $svcPort }}
{{- end }}
{{- end }}
