{{/*
Reusable ServiceAccount. Rendered with:
  {{ include "watertwin-common.serviceaccount" . }}
*/}}
{{- define "watertwin-common.serviceaccount" -}}
{{- if .Values.serviceAccount.create -}}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "watertwin-common.serviceAccountName" . }}
  labels:
    {{- include "watertwin-common.labels" . | nindent 4 }}
  {{- with .Values.serviceAccount.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
automountServiceAccountToken: {{ .Values.serviceAccount.automount | default false }}
{{- end -}}
{{- end -}}
