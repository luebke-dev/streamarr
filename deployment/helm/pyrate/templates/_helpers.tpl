{{/*
Common helpers — name, fullname, labels, image refs, secret refs.
*/}}

{{- define "pyrate.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "pyrate.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "pyrate.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "pyrate.labels" -}}
helm.sh/chart: {{ include "pyrate.chart" . }}
app.kubernetes.io/name: {{ include "pyrate.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}

{{/*
Per-component selector labels. Pass a dict { "ctx": ., "component": "backend-python" }.
*/}}
{{- define "pyrate.selectorLabels" -}}
app.kubernetes.io/name: {{ include "pyrate.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "pyrate.componentLabels" -}}
{{ include "pyrate.labels" .ctx }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/*
Service hostname helpers — unqualified, relies on cluster DNS within the
release namespace. Postgres / Redis / Elasticsearch use the chart-managed
StatefulSets; the helpers stay valid even if the user later swaps them out
for external endpoints by setting `*.enabled=false` and overriding the URLs.
*/}}
{{- define "pyrate.postgresHost" -}}
{{- if .Values.postgres.enabled -}}
{{- printf "%s-postgres" (include "pyrate.fullname" .) -}}
{{- else -}}
{{- required "postgres.external.host is required when postgres.enabled=false" .Values.postgres.external.host -}}
{{- end -}}
{{- end -}}

{{- define "pyrate.postgresPort" -}}
{{- if .Values.postgres.enabled -}}
{{- .Values.postgres.service.port -}}
{{- else -}}
{{- .Values.postgres.external.port -}}
{{- end -}}
{{- end -}}

{{- define "pyrate.postgresUser" -}}
{{- if .Values.postgres.enabled -}}
{{- .Values.postgres.user -}}
{{- else -}}
{{- .Values.postgres.external.user -}}
{{- end -}}
{{- end -}}

{{- define "pyrate.postgresDatabase" -}}
{{- if .Values.postgres.enabled -}}
{{- .Values.postgres.database -}}
{{- else -}}
{{- .Values.postgres.external.database -}}
{{- end -}}
{{- end -}}

{{/*
Render the env entry that pulls the postgres password out of a Secret. For
the in-tree cluster we use the chart-managed Secret; for an external one we
reference the user's existing secret (e.g. CloudNativePG's `<cluster>-app`).
*/}}
{{- define "pyrate.postgresPasswordEnv" -}}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
{{- if .Values.postgres.enabled }}
      name: {{ include "pyrate.secretName" . }}
      key: postgres-password
{{- else }}
      name: {{ required "postgres.external.existingSecret.name is required when postgres.enabled=false" .Values.postgres.external.existingSecret.name | quote }}
      key: {{ .Values.postgres.external.existingSecret.passwordKey | quote }}
{{- end }}
{{- end -}}

{{- define "pyrate.redisHost" -}}
{{- printf "%s-redis" (include "pyrate.fullname" .) -}}
{{- end -}}

{{- define "pyrate.elasticsearchHost" -}}
{{- printf "%s-elasticsearch" (include "pyrate.fullname" .) -}}
{{- end -}}

{{- define "pyrate.backendHost" -}}
{{- printf "%s-backend" (include "pyrate.fullname" .) -}}
{{- end -}}

{{- define "pyrate.lightraysHost" -}}
{{- printf "%s-lightrays" (include "pyrate.fullname" .) -}}
{{- end -}}

{{/*
Derive the browser-facing public URL for Lightrays. Precedence:
  1. Operator-provided lightrays.publicUrl (any explicit value wins).
  2. Auto-derived from ingress when both ingress and lightrays are enabled:
     {scheme}://{ingress.host}{ingress.paths.lightrays}
     (scheme is https when TLS is configured, http otherwise).
  3. Empty — the frontend then falls back to a same-origin relative path.
*/}}
{{- define "pyrate.lightraysPublicUrl" -}}
{{- if .Values.lightrays.publicUrl -}}
{{- .Values.lightrays.publicUrl -}}
{{- else if and .Values.ingress.enabled .Values.lightrays.enabled -}}
{{- $scheme := ternary "https" "http" (ne (toString .Values.ingress.tls.secretName) "") -}}
{{- $path := trimSuffix "/" .Values.ingress.paths.lightrays -}}
{{- printf "%s://%s%s" $scheme .Values.ingress.host $path -}}
{{- end -}}
{{- end -}}

{{- define "pyrate.computeServiceAccountName" -}}
{{- default (printf "%s-compute" (include "pyrate.fullname" .)) .Values.rbac.serviceAccount.name -}}
{{- end -}}

{{- define "pyrate.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "pyrate.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Render an image reference. Pass a dict with { "registry": "...", "repository": "...", "tag": "..." }.
Falls back to global.imageRegistry when registry is empty.
*/}}
{{- define "pyrate.image" -}}
{{- $registry := default .ctx.Values.global.imageRegistry .img.registry -}}
{{- $repo := .img.repository -}}
{{- $tag := default "latest" .img.tag -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $repo $tag -}}
{{- else -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end -}}

{{/*
Render `imagePullSecrets:`. Accepts both shapes — a list of plain
strings or the canonical Helm `[{name: "..."}]` dict form — so callers
can use whichever feels natural without tripping over Go's default
template rendering of map values.
*/}}
{{- define "pyrate.imagePullSecrets" -}}
{{- with .Values.global.imagePullSecrets -}}
imagePullSecrets:
{{- range . }}
{{- if kindIs "string" . }}
  - name: {{ . }}
{{- else if kindIs "map" . }}
  - name: {{ .name }}
{{- end }}
{{- end }}
{{- end -}}
{{- end -}}

{{/*
Common environment variables shared by backend-python / worker / scheduler.
Pulls passwords from the Secret produced by secrets.yaml.
*/}}
{{- define "pyrate.commonEnv" -}}
- name: POSTGRES_USER
  value: {{ include "pyrate.postgresUser" . | quote }}
- name: POSTGRES_DB
  value: {{ include "pyrate.postgresDatabase" . | quote }}
{{ include "pyrate.postgresPasswordEnv" . }}
- name: SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "pyrate.secretName" . }}
      key: secret-key
- name: LIGHTRAYS_JWT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "pyrate.secretName" . }}
      key: lightrays-jwt-secret
- name: REDIS_URL
  value: "redis://{{ include "pyrate.redisHost" . }}:{{ .Values.redis.service.port }}/0"
- name: ELASTICSEARCH_HOST
  value: {{ include "pyrate.elasticsearchHost" . | quote }}
- name: ELASTICSEARCH_PORT
  value: {{ .Values.elasticsearch.service.port | quote }}
- name: LIGHTRAYS_URL
  value: "http://{{ include "pyrate.lightraysHost" . }}:{{ .Values.lightrays.service.apiPort }}"
- name: LIGHTRAYS_PUBLIC_URL
  value: {{ include "pyrate.lightraysPublicUrl" . | quote }}
- name: LIGHTRAYS_DEFAULT_RUNTIME_PROFILE
  value: {{ .Values.lightrays.defaultRuntimeProfile | quote }}
- name: LIGHTRAYS_SESSION_TIMEOUT_SECS
  value: {{ .Values.lightrays.sessionTimeoutSeconds | quote }}
# PVC names spawned compute Jobs reuse for /library, /downloads,
# /cache, /temp. Backend's services/computing.py:build_media_volumes
# reads these and routes the values to the Kubernetes computing
# provider, which mounts the same RWX PVCs the parent pod uses.
- name: PYRATE_PVC_LIBRARY
  value: {{ printf "%s-library" (include "pyrate.fullname" .) | quote }}
- name: PYRATE_PVC_DOWNLOADS
  value: {{ printf "%s-downloads" (include "pyrate.fullname" .) | quote }}
- name: PYRATE_PVC_CACHE
  value: {{ printf "%s-cache" (include "pyrate.fullname" .) | quote }}
- name: PYRATE_PVC_TEMP
  value: {{ printf "%s-temp" (include "pyrate.fullname" .) | quote }}
{{- end -}}

{{- define "pyrate.databaseUrlAsync" -}}
postgresql+asyncpg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@{{ include "pyrate.postgresHost" . }}:{{ include "pyrate.postgresPort" . }}/$(POSTGRES_DB)
{{- end -}}

{{- define "pyrate.databaseUrlSync" -}}
postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@{{ include "pyrate.postgresHost" . }}:{{ include "pyrate.postgresPort" . }}/$(POSTGRES_DB)
{{- end -}}

{{/*
The five shared data subdirectories. Each maps to a PVC in `pvc` mode or a
hostPath at `<persistence.hostPath.base>/data/<key>` in `hostPath` mode. The
hostPath layout matches what `services/computing.py:_data_root()` expects so
spawned FFmpeg Job pods can bind-mount the same directories.
*/}}
{{- define "pyrate.dataVolumeKeys" -}}
library
downloads
cache
temp
users
{{- end -}}

{{- define "pyrate.dataVolumes" -}}
{{- $base := .Values.persistence.hostPath.base -}}
{{- $mode := default "pvc" .Values.persistence.mode -}}
{{- range $key := splitList "\n" (include "pyrate.dataVolumeKeys" .) }}
{{- $key := trim $key }}{{- if $key }}
- name: {{ $key }}
  {{- if eq $mode "hostPath" }}
  hostPath:
    path: {{ $base }}/data/{{ $key }}
    type: DirectoryOrCreate
  {{- else }}
  persistentVolumeClaim:
    claimName: {{ include "pyrate.fullname" $ }}-{{ $key }}
  {{- end }}
{{- end }}{{- end }}
{{- end -}}

{{- define "pyrate.dataVolumeMounts" -}}
- { name: library,   mountPath: /library }
- { name: downloads, mountPath: /downloads }
- { name: cache,     mountPath: /cache }
- { name: temp,      mountPath: /temp }
- { name: users,     mountPath: /user-data }
{{- end -}}
