#!/bin/sh
set -eu

: "${PROMETHEUS_HOST:?PROMETHEUS_HOST must be set}"
: "${PROMETHEUS_PORT:?PROMETHEUS_PORT must be set}"

export GF_PATHS_PROVISIONING="${GF_PATHS_PROVISIONING:-/tmp/provisioning}"

tmpl="$GF_PATHS_PROVISIONING/datasources/datasource.yaml.template"
out="$GF_PATHS_PROVISIONING/datasources/datasource.yaml"

sed \
  -e "s|\${PROMETHEUS_HOST}|${PROMETHEUS_HOST}|g" \
  -e "s|\${PROMETHEUS_PORT}|${PROMETHEUS_PORT}|g" \
  "$tmpl" > "$out"

exec /run.sh
