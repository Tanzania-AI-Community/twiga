# Monitoring stack

This folder contains the Prometheus + Grafana setup for Twiga.

## Components
- `docker-compose.monitoring.yml`: brings up Prometheus (9090) and Grafana (4000).
- `prometheus/prometheus.yml`: Prometheus scrape config and alerts.
- `grafana/provisioning/datasources/datasource.yaml`: wires Grafana to Prometheus (`uid: prometheus`).
- `grafana/provisioning/dashboards/dashboards.yaml`: auto-loads JSON dashboards from `grafana/provisioning/dashboards/json` into folder "Twiga".

## Dashboards (grafana/provisioning/dashboards/json)
- `fastapi-overview.json`: FastAPI request rate, latency, error rates, in-flight requests.
- `llm-performance.json`: LLM call counts, latency, success/error breakdown.

## Running locally
```bash
cd monitoring
docker compose -f docker-compose.monitoring.yml up
```
- Prometheus: http://localhost:9090
- Grafana: http://localhost:4000 (anonymous view enabled)
