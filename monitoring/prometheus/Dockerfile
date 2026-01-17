FROM prom/prometheus:v2.55.0

COPY monitoring/prometheus/prometheus.yml.template /etc/prometheus/prometheus.yml.template
COPY monitoring/prometheus/entrypoint.sh /entrypoint.sh

EXPOSE 9090
ENTRYPOINT ["/entrypoint.sh"]
