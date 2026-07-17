{{/*
Optional Ingress. Rendered with: {{ include "watertwin-common.ingress" . }}
Disabled by default; enabled per-environment (staging/prod) for the dashboard
and API only.
*/}}
{{- define "watertwin-common.ingress" -}}
{{- if .Values.ingress.enabled -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "watertwin-common.fullname" . }}
  labels:
    {{- include "watertwin-common.labels" . | nindent 4 }}
  {{- with .Values.ingress.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- with .Values.ingress.className }}
  ingressClassName: {{ . }}
  {{- end }}
  {{- with .Values.ingress.tls }}
  tls:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  rules:
    {{- range .Values.ingress.hosts }}
    - host: {{ .host | quote }}
      http:
        paths:
          {{- range .paths }}
          - path: {{ .path }}
            pathType: {{ .pathType | default "Prefix" }}
            backend:
              service:
                name: {{ include "watertwin-common.fullname" $ }}
                port:
                  number: {{ .servicePort }}
          {{- end }}
    {{- end }}
{{- end -}}
{{- end -}}
