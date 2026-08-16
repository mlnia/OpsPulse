# Case study: OpsPulse

## Problem

During an incident, engineers often switch between monitoring tools, chat channels, and issue trackers. This fragmentation makes it harder to establish ownership, track progress, and measure operational outcomes such as MTTR.

## Solution

OpsPulse is a focused incident-operations dashboard. It gives responders a single place to create and progress incidents, review an audit trail, capture operational context, and observe API health.

## Key engineering decisions

| Decision | Rationale |
| --- | --- |
| FastAPI + PostgreSQL | Typed, fast API development with a relational source of truth for operational records. |
| Redis Streams + worker | Notification delivery is decoupled from the incident request path. |
| JWT + RBAC | Read-only viewers cannot create or mutate incidents; responders and admins can. |
| Nginx rate limiting | Protects the API boundary from accidental or malicious bursts. |
| Prometheus, Grafana, OpenTelemetry | Makes service health, latency, errors, and traces observable. |
| Kubernetes + Helm | Demonstrates an environment-agnostic deployment path with scalable services. |

## Demonstrated outcomes

- Incident updates are persisted with actor-level auditability.
- Slack notifications can be enabled without coupling third-party I/O to the API request.
- The dashboard exposes the active incident count and critical-incident signal at a glance.
- Automated tests and a k6 load-test scenario provide a baseline quality and performance workflow.

## Future extensions

- Send traces to Grafana Tempo and correlate them with incident records.
- Add SSO/OIDC and automated user provisioning.
- Add alert routing and on-call scheduling integrations.
- Deploy images to GHCR from CI and promote releases through staging and production environments.
