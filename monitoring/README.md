# Monitoring stack

This folder contains the Prometheus + Grafana setup for Twiga.

## Components
- `docker-compose.monitoring.yml`: brings up Prometheus (9090) and Grafana (3000).
- `prometheus/prometheus.yml`: Prometheus scrape config and alerts.
- `grafana/provisioning/datasources/datasource.yaml`: wires Grafana to Prometheus (`uid: prometheus`).
- `grafana/provisioning/dashboards/dashboards.yaml`: auto-loads JSON dashboards from `grafana/provisioning/dashboards/json` into folder "Twiga".

## Dashboards (grafana/provisioning/dashboards/json)
- `fastapi-overview.json`: FastAPI request rate, latency, error rates, in-flight requests.
- `llm-performance.json`: LLM call counts, latency, success/error breakdown.
- `redis.json`: Redis ops/memory/latency (via `redis_exporter` -> `redis:6379`).

## Running locally
```bash
cd monitoring
docker compose -f docker-compose.monitoring.yml up
```
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (anonymous view enabled)

## Notes
- Redis/exporter is included only to scrape Redis metrics. If you already run Redis elsewhere, point `REDIS_ADDR` to it; if you don't need Redis metrics, you can remove the `redis`/`redis_exporter` services and the Prometheus dependency on the exporter.
