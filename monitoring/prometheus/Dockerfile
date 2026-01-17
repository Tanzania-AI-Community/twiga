FROM prom/prometheus:v2.55.0

COPY monitoring/prometheus/prometheus.yml.tmpl /etc/prometheus/prometheus.yml.tmpl
COPY monitoring/prometheus/entrypoint.sh /entrypoint.sh

EXPOSE 9090
ENTRYPOINT ["/entrypoint.sh"]
