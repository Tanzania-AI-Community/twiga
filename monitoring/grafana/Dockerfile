FROM grafana/grafana:11.2.0

USER root

COPY monitoring/grafana/provisioning /usr/share/grafana/conf/provisioning

COPY monitoring/grafana/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 4000 
ENTRYPOINT ["/entrypoint.sh"]
