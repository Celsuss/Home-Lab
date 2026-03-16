{{- define "homelab-common.tailscale-ingress" -}}
{{- if .Values.tailscale.enabled }}
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
                name: {{ .serviceName | default (.Values.tailscale.serviceName | default .fullname) }}
                port:
                  number: {{ .servicePort | default (.Values.tailscale.servicePort | default .Values.service.port) }}
{{- end }}
{{- end }}
