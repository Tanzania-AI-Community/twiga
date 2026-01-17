FROM grafana/grafana:11.2.0

COPY monitoring/grafana/provisioning /etc/grafana/provisioning
COPY monitoring/grafana/entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
