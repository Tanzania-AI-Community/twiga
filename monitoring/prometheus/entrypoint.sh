#!/bin/sh
set -eu

ENVIRONMENT="${ENVIRONMENT:-local}"

if [ "$ENVIRONMENT" = "production" ]; then
: "${TWIGA_INTERNAL_HOST:?TWIGA_INTERNAL_HOST must be set in production}"  # Important: this is the name of the service in Render!
  : "${TWIGA_INTERNAL_PORT:=8000}"
  export TWIGA_METRICS_TARGET="${TWIGA_INTERNAL_HOST}:${TWIGA_INTERNAL_PORT}"
else
  export TWIGA_METRICS_TARGET="${TWIGA_LOCAL_TARGET:-host.docker.internal:8000}"
fi

envsubst < /etc/prometheus/prometheus.yml.template > /etc/prometheus/prometheus.yml

echo "ENVIRONMENT=$ENVIRONMENT"
echo "TWIGA_METRICS_TARGET=$TWIGA_METRICS_TARGET"

exec /bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus
