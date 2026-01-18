#!/bin/sh
set -eu

ENVIRONMENT="${ENVIRONMENT:-local}"

if [ "$ENVIRONMENT" = "production" ]; then
  : "${TWIGA_INTERNAL_HOST:?TWIGA_INTERNAL_HOST must be set in production}"
  : "${TWIGA_INTERNAL_PORT:=8000}"
  TWIGA_METRICS_TARGET="${TWIGA_INTERNAL_HOST}:${TWIGA_INTERNAL_PORT}"
else
  TWIGA_METRICS_TARGET="${TWIGA_LOCAL_TARGET:-host.docker.internal:8000}"
fi

cat > /etc/prometheus/prometheus.yml <<EOF
global:
  scrape_interval: 30s
  evaluation_interval: 30s

rule_files:
  - /etc/prometheus/alerts.yml

scrape_configs:
  - job_name: "twiga-app"
    metrics_path: /metrics
    static_configs:
      - targets:
          - ${TWIGA_METRICS_TARGET}
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        replacement: twiga-app
EOF

echo "ENVIRONMENT=$ENVIRONMENT"
echo "TWIGA_METRICS_TARGET=$TWIGA_METRICS_TARGET"

exec /bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus
