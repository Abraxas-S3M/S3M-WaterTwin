{{/*
OT-aware NetworkPolicy for a component. Rendered with:
  {{ include "watertwin-common.networkpolicy" . }}

The platform inherits the S3M read-only / advisory posture. This template
encodes that at the network layer:

  * Every component gets an explicit Ingress + Egress allow-list on top of the
    namespace default-deny. Anything not listed is denied.
  * OT reachability is *outbound-only*: the edge-gateway (and any OT connector)
    may only ever INITIATE connections toward an OT segment CIDR on a read-only
    protocol port. OT segments can never open a connection back into the
    platform, because no component lists an OT CIDR as an ingress peer. This
    mirrors the read-only OT connector contract in
    docs/security/control-boundaries.md.

Peer shapes accepted by `from:` / `to:` lists:
  - {component: <name>[, namespace: <ns>]}  -> pod selector (optionally scoped)
  - {namespace: <ns>}                       -> namespace selector
  - {cidr: <cidr>[, except: [<cidr>...]]}   -> ipBlock (used for OT egress)
  - {namespaceSelector: {...}}              -> raw namespace selector
  - {podSelector: {...}}                    -> raw pod selector
*/}}
{{- define "watertwin-common.netpolPeer" -}}
{{- $peer := .peer -}}
{{- $root := .root -}}
{{- if $peer.component -}}
- podSelector:
    matchLabels:
      app.kubernetes.io/name: {{ $peer.component }}
      app.kubernetes.io/instance: {{ $root.Release.Name }}
  {{- with $peer.namespace }}
  namespaceSelector:
    matchLabels:
      kubernetes.io/metadata.name: {{ . }}
  {{- end }}
{{- else if $peer.cidr -}}
- ipBlock:
    cidr: {{ $peer.cidr }}
    {{- with $peer.except }}
    except:
      {{- range . }}
      - {{ . }}
      {{- end }}
    {{- end }}
{{- else if $peer.namespace -}}
- namespaceSelector:
    matchLabels:
      kubernetes.io/metadata.name: {{ $peer.namespace }}
{{- else if $peer.namespaceSelector -}}
- namespaceSelector:
    {{- toYaml $peer.namespaceSelector | nindent 4 }}
{{- else if $peer.podSelector -}}
- podSelector:
    {{- toYaml $peer.podSelector | nindent 4 }}
{{- end -}}
{{- end -}}

{{- define "watertwin-common.networkpolicy" -}}
{{- if .Values.networkPolicy.enabled -}}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "watertwin-common.fullname" . }}
  labels:
    {{- include "watertwin-common.labels" . | nindent 4 }}
  annotations:
    watertwin.s3m.io/posture: "advisory-read-only; OT egress is outbound-only"
spec:
  podSelector:
    matchLabels:
      {{- include "watertwin-common.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    {{- range .Values.networkPolicy.ingress }}
    -
      {{- with .ports }}
      ports:
        {{- range . }}
        - protocol: {{ .protocol | default "TCP" }}
          port: {{ .port }}
        {{- end }}
      {{- end }}
      {{- with .from }}
      from:
        {{- range . }}
        {{- include "watertwin-common.netpolPeer" (dict "peer" . "root" $) | nindent 8 }}
        {{- end }}
      {{- end }}
    {{- end }}
  egress:
    {{- if .Values.networkPolicy.allowDNS }}
    # Cluster DNS resolution (kube-dns / CoreDNS) is always required.
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    {{- end }}
    {{- range .Values.networkPolicy.egress }}
    -
      {{- with .ports }}
      ports:
        {{- range . }}
        - protocol: {{ .protocol | default "TCP" }}
          port: {{ .port }}
        {{- end }}
      {{- end }}
      {{- with .to }}
      to:
        {{- range . }}
        {{- include "watertwin-common.netpolPeer" (dict "peer" . "root" $) | nindent 8 }}
        {{- end }}
      {{- end }}
    {{- end }}
{{- end -}}
{{- end -}}
