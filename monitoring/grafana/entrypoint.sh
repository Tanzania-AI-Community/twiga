#!/bin/sh
set -eu

: "${PROMETHEUS_HOST:?PROMETHEUS_HOST must be set}"
: "${PROMETHEUS_PORT:?PROMETHEUS_PORT must be set}"

<<<<<<< Updated upstream
GF_PATHS_PROVISIONING="${GF_PATHS_PROVISIONING:-/tmp/provisioning}"
=======
DATASOURCE_DIR="/etc/grafana/provisioning/datasources"
DATASOURCE_FILE="$DATASOURCE_DIR/datasource.yaml"
>>>>>>> Stashed changes

mkdir -p "$DATASOURCE_DIR"

<<<<<<< Updated upstream
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
=======
cat > "$DATASOURCE_FILE" <<EOF
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
>>>>>>> Stashed changes

exec /run.sh
