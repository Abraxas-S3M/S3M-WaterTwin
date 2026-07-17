{{/*
Reusable ClusterIP Service. Rendered with:
  {{ include "watertwin-common.service" . }}
*/}}
{{- define "watertwin-common.service" -}}
{{- if .Values.service.enabled -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "watertwin-common.fullname" . }}
  labels:
    {{- include "watertwin-common.labels" . | nindent 4 }}
  {{- with .Values.service.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  type: {{ .Values.service.type | default "ClusterIP" }}
  {{- with .Values.service.clusterIP }}
  clusterIP: {{ . }}
  {{- end }}
  selector:
    {{- include "watertwin-common.selectorLabels" . | nindent 4 }}
  ports:
    {{- range .Values.service.ports }}
    - name: {{ .name }}
      port: {{ .port }}
      targetPort: {{ .targetPort | default .name }}
      protocol: {{ .protocol | default "TCP" }}
    {{- end }}
{{- end -}}
{{- end -}}

{{/*
Headless Service used as the StatefulSet governing service. Rendered with:
  {{ include "watertwin-common.headlessService" . }}
*/}}
{{- define "watertwin-common.headlessService" -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "watertwin-common.fullname" . }}-headless
  labels:
    {{- include "watertwin-common.labels" . | nindent 4 }}
spec:
  clusterIP: None
  publishNotReadyAddresses: true
  selector:
    {{- include "watertwin-common.selectorLabels" . | nindent 4 }}
  ports:
    {{- range .Values.service.ports }}
    - name: {{ .name }}
      port: {{ .port }}
      targetPort: {{ .targetPort | default .name }}
      protocol: {{ .protocol | default "TCP" }}
    {{- end }}
{{- end -}}
