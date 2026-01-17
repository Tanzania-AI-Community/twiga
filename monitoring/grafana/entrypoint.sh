#!/bin/sh
set -eu

: "${PROMETHEUS_HOST:=localhost}"
: "${PROMETHEUS_PORT:=9090}"

envsubst < /etc/grafana/provisioning/datasources/datasource.yaml.template \
         > /etc/grafana/provisioning/datasources/datasource.yaml

exec /run.sh
