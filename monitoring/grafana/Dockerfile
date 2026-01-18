FROM grafana/grafana:11.2.0

USER root

COPY provisioning /tmp/provisioning
COPY entrypoint.sh /entrypoint.sh

RUN chmod -R a+rwX /tmp/provisioning && chmod +x /entrypoint.sh

EXPOSE 3000
ENTRYPOINT ["/entrypoint.sh"]
