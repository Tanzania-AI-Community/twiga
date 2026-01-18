FROM grafana/grafana:11.2.0

USER root

COPY monitoring/grafana/provisioning /tmp/provisioning
COPY monitoring/grafana/entrypoint.sh /entrypoint.sh

# Don't assume grafana user exists; just make it writable
RUN chmod -R a+rwX /tmp/provisioning && chmod +x /entrypoint.sh

EXPOSE 3000
ENTRYPOINT ["/entrypoint.sh"]
