FROM prom/prometheus:v2.55.0

USER root

COPY monitoring/prometheus/alerts.yml /etc/prometheus/alerts.yml
COPY monitoring/prometheus/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 9090
ENTRYPOINT ["/entrypoint.sh"]
