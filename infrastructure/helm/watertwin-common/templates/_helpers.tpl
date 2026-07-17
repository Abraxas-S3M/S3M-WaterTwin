{{/*
Shared naming / labelling helpers for the S3M-WaterTwin component charts.
Every helper is called with the *consuming subchart's* context, so `.Chart`,
`.Values` and `.Release` resolve to that component while `.Release` stays shared
across the umbrella release.
*/}}

{{- define "watertwin-common.name" -}}
{{- .Values.nameOverride | default .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Fully-qualified component name: "<release>-<component>" unless fullnameOverride
is set. Truncated to the 63-char DNS label limit.
*/}}
{{- define "watertwin-common.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := .Values.nameOverride | default .Chart.Name -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/*
Selector labels. These are stable across upgrades and are the labels that
NetworkPolicy peers match on, so keep them minimal.
*/}}
{{- define "watertwin-common.selectorLabels" -}}
app.kubernetes.io/name: {{ include "watertwin-common.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "watertwin-common.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name (.Chart.Version | toString) | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "watertwin-common.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: watertwin
{{- with .Values.componentTier }}
watertwin.s3m.io/tier: {{ . | quote }}
{{- end }}
{{- end -}}

{{/*
Resolve the container image reference. Honours a global image registry
(`global.imageRegistry`) and defaults the tag to the chart appVersion.
*/}}
{{- define "watertwin-common.image" -}}
{{- $img := .Values.image -}}
{{- $g := .Values.global | default dict -}}
{{- $registry := $img.registry | default $g.imageRegistry -}}
{{- $repo := $img.repository -}}
{{- $tag := $img.tag | default .Chart.AppVersion | default "latest" | toString -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $repo $tag -}}
{{- else -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end -}}

{{- define "watertwin-common.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- .Values.serviceAccount.name | default (include "watertwin-common.fullname" .) -}}
{{- else -}}
{{- .Values.serviceAccount.name | default "default" -}}
{{- end -}}
{{- end -}}

{{/*
Container env block. Merges three sources without ever inlining a secret value:
  * .Values.env       -> plain key/value pairs (non-sensitive config)
  * .Values.secretEnv -> [{name, secretName, secretKey}] rendered as secretKeyRef
  * .Values.extraEnv  -> raw env entries (e.g. fieldRef / configMapKeyRef)
*/}}
{{- define "watertwin-common.env" -}}
{{- if or .Values.env .Values.secretEnv .Values.extraEnv -}}
env:
  {{- range $k, $v := .Values.env }}
  - name: {{ $k }}
    value: {{ tpl ($v | toString) $ | quote }}
  {{- end }}
  {{- range .Values.secretEnv }}
  - name: {{ .name }}
    valueFrom:
      secretKeyRef:
        name: {{ .secretName }}
        key: {{ .secretKey }}
        {{- if hasKey . "optional" }}
        optional: {{ .optional }}
        {{- end }}
  {{- end }}
  {{- with .Values.extraEnv }}
  {{- toYaml . | nindent 2 }}
  {{- end }}
{{- end -}}
{{- end -}}
