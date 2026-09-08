{{/*
Expand the name of the chart.
*/}}
{{- define "servicex-mcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "servicex-mcp.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart name and version label value.
*/}}
{{- define "servicex-mcp.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "servicex-mcp.labels" -}}
helm.sh/chart: {{ include "servicex-mcp.chart" . }}
{{ include "servicex-mcp.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels.
*/}}
{{- define "servicex-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "servicex-mcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount name to use.
*/}}
{{- define "servicex-mcp.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "servicex-mcp.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Validate the auth configuration. Fails the render early with a clear message
rather than producing a manifest the server would reject at startup.
*/}}
{{- define "servicex-mcp.validate" -}}
{{- if not .Values.auth.backendUrl -}}
{{- fail "auth.backendUrl is required: the base URL of the ServiceX deployment this server talks to" -}}
{{- end -}}
{{- end }}

{{/*
Public resource URL: explicit value, else derived from ingress host. Required
for HTTP transport (used to build OAuth redirect URIs and the DNS-rebinding
protection allow-list).
*/}}
{{- define "servicex-mcp.resourceUrl" -}}
{{- if .Values.auth.resourceUrl -}}
{{- .Values.auth.resourceUrl -}}
{{- else if .Values.ingress.host -}}
{{- printf "https://%s" .Values.ingress.host -}}
{{- else -}}
{{- fail "auth.resourceUrl or ingress.host must be set" -}}
{{- end -}}
{{- end }}

{{/*
Build the `servicex-mcp serve` argument string from values. Mirrors the actual
CLI surface in src/servicex_mcp/cli.py -- there is no --site/--auth-type/
--metrics-port/--forwarded-allow-ips here, unlike rucio-mcp: this server has
one ServiceX backend per deployment and no Prometheus metrics module yet.
*/}}
{{- define "servicex-mcp.serveArgs" -}}
{{- include "servicex-mcp.validate" . -}}
{{- $args := list "--transport" "http"
    "--backend-url" .Values.auth.backendUrl
    "--resource-url" (include "servicex-mcp.resourceUrl" .)
    "--host" (.Values.server.host | toString)
    "--port" (.Values.server.port | toString)
    "--cache-dir" .Values.server.cacheDir
    "--log-level" .Values.logLevel -}}
{{- if .Values.readOnly -}}
{{- $args = append $args "--read-only" -}}
{{- end -}}
{{- $args | join " " -}}
{{- end }}
