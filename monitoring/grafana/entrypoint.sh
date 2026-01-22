#!/bin/sh
set -eu

: "${PROMETHEUS_HOST:?PROMETHEUS_HOST must be set}"
: "${PROMETHEUS_PORT:?PROMETHEUS_PORT must be set}"

DATASOURCE_DIR="/usr/share/grafana/conf/provisioning/datasources"
DATASOURCE_FILE="$DATASOURCE_DIR/datasource.yaml"

mkdir -p "$DATASOURCE_DIR"

cat <<EOF > "$DATASOURCE_FILE"
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://${PROMETHEUS_HOST}:${PROMETHEUS_PORT}
    isDefault: true
    editable: false
EOF

cat "$DATASOURCE_FILE"

exec /run.sh
