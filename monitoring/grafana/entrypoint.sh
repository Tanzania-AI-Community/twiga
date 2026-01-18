#!/bin/sh
set -eu

: "${PROMETHEUS_HOST:?PROMETHEUS_HOST must be set}"
: "${PROMETHEUS_PORT:?PROMETHEUS_PORT must be set}"

GF_PATHS_PROVISIONING="${GF_PATHS_PROVISIONING:-/tmp/provisioning}"

tmpl="$GF_PATHS_PROVISIONING/datasources/datasource.yaml.template"
out="$GF_PATHS_PROVISIONING/datasources/datasource.yaml"

mkdir -p "$(dirname "$out")"

if [ ! -f "$tmpl" ]; then
  echo "Datasource template not found at: $tmpl" >&2
  echo "Contents of provisioning dir:" >&2
  ls -la "$GF_PATHS_PROVISIONING" >&2 || true
  find "$GF_PATHS_PROVISIONING" -maxdepth 2 -type f -print >&2 || true
  exit 1
fi

sed \
  -e "s|\${PROMETHEUS_HOST}|${PROMETHEUS_HOST}|g" \
  -e "s|\${PROMETHEUS_PORT}|${PROMETHEUS_PORT}|g" \
  "$tmpl" > "$out"

exec /run.sh
