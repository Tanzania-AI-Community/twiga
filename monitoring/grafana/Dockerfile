FROM grafana/grafana:11.2.0

USER root

COPY provisioning /usr/share/grafana/conf/provisioning

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 3000
ENTRYPOINT ["/entrypoint.sh"]
