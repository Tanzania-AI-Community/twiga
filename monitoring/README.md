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
  Also shows teacher profile updates (name, subjects and forms) by result.

## Onboarding

Teachers onboard by chatting: the agent saves their name and classes through
the profile tools, and the server marks onboarding complete once both are saved.

**Profile updates** (`twiga_profile_updates_total{field, result}`, panel
"Profile Updates by Result"): `result` is `ok` or why the save was refused
(`invalid_name`, `unknown_subject`, `missing_forms`, `limit_exceeded`, ...).
A rising share of refusals usually means a model or prompt regression, e.g. the
model passing the whole sentence as the name. `unknown_subject` shows demand for
subjects that are not available yet.

**Funnel**: the `users` table already holds it, so it is queried rather than
counted in Prometheus (counters reset on restart). Run against production;
outside production new users get a dummy profile and skip onboarding.

```sql
-- Where teachers who registered in the last 30 days are now
SELECT
  CASE
    WHEN onboarding_state = 'completed' THEN '3. completed'
    WHEN onboarding_state = 'personal_info_submitted' THEN '2. name saved, no classes'
    WHEN state = 'onboarding' THEN '1. started, nothing saved'
    ELSE 'other (e.g. in review)'
  END AS step,
  count(*) AS teachers
FROM users
WHERE role = 'teacher'
  AND created_at >= now() - interval '30 days'
GROUP BY step
ORDER BY step;

-- Teachers stuck in onboarding for more than 2 days
SELECT onboarding_state, count(*) AS teachers
FROM users
WHERE state = 'onboarding'
  AND created_at < now() - interval '2 days'
GROUP BY onboarding_state;
```

## Running locally
```bash
cd monitoring
docker compose -f docker-compose.monitoring.yml up
```
- Prometheus: http://localhost:9090
- Grafana: http://localhost:4000 (anonymous view enabled)
