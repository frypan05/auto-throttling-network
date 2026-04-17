# Nginx Load Balancer — FastAPI · GraphQL · Prometheus · Grafana

A self-contained Docker project that demonstrates **Nginx least-connection load
balancing** across four Python/GraphQL servers, with live Prometheus metrics and
a pre-built Grafana dashboard.

---

## Architecture

```
                        ┌─────────────────────────────────────────────────┐
                        │                  Docker Network                 │
                        │                                                 │
  ┌──────────┐  HTTP    │  ┌─────────────┐       ┌────────────────────┐   │
  │  Client  │ ───────► │  │  Nginx :80  │──┬──► │  server-1 :8000    │   │
  │ (aiohttp)│          │  │ least_conn  │  ├──► │  server-2 :8000    │   │
  └──────────┘          │  └─────────────┘  ├──► │  server-3 :8000    │   │
                        │                   └──► │  server-4 :8000    │   │
                        │                        └────────┬───────────┘   │
                        │                                 │ /metrics      │
                        │  ┌──────────────┐    ┌─────────▼──────────┐     │
                        │  │ Grafana :3000│◄───│ Prometheus :9090   │     │
                        │  │  Dashboard   │    │  scrape every 5s   │     │
                        │  └──────────────┘    └────────────────────┘     │
                        └─────────────────────────────────────────────────┘
```

### Services at a Glance

| Service        | Port | Description                                  |
|----------------|------|----------------------------------------------|
| `nginx`        | 80   | Load balancer — `least_conn` algorithm       |
| `server-1..4`  | —    | FastAPI + Strawberry GraphQL + `/metrics`    |
| `client`       | —    | Async traffic generator (no exposed port)    |
| `prometheus`   | 9090 | Metrics scraper                              |
| `grafana`      | 3000 | Dashboards — login `admin` / `admin`         |

---

## Quick Start

```bash
# 1. Clone / unzip the project
cd nginx-lb-demo

# 2. Build images and start everything
docker compose up --build

# 3. Watch the client output live (optional)
docker compose logs -f client
```

| URL                          | What you'll see                        |
|------------------------------|----------------------------------------|
| http://localhost/graphql     | GraphQL Playground (via Nginx LB)      |
| http://localhost/nginx_status| Nginx stub_status page                 |
| http://localhost:9090        | Prometheus query UI                    |
| http://localhost:3000        | Grafana dashboard (auto-opens)         |

---

## GraphQL Endpoints

All five queries are available at `POST /graphql` through Nginx.

```graphql
# Which server handled this request?
query { serverInfo { serverId load uptime message } }

# Product catalogue (with optional category filter)
query { getProducts(limit: 5, category: "electronics") { id name price inStock } }

# User list
query { getUsers(limit: 10) { id name email role } }

# CPU-intensive computation (triggers higher latency)
query { computeHeavy(iterations: 8000) { value elapsedMs serverId } }

# Order lookup
query { getOrders(limit: 3) { orderId total status } }
```

---

## Load Balancing Algorithms

The algorithm is set in `nginx/nginx.conf` inside the `upstream` block.

```nginx
upstream graphql_backends {
    least_conn;          # ← current: fewest active connections
    # ip_hash;           # ← sticky sessions by client IP
    # (remove both)      # ← default: round-robin

    server server-1:8000;
    server server-2:8000;
    server server-3:8000;
    server server-4:8000;
    keepalive 32;
}
```

After changing the config, reload without downtime:

```bash
docker compose exec nginx nginx -s reload
```

---

## Prometheus Metrics Exposed

Every server publishes these metrics at `GET /metrics`:

| Metric                                    | Type      | Description                           |
|-------------------------------------------|-----------|---------------------------------------|
| `app_graphql_requests_total`              | Counter   | Total requests, labelled by query     |
| `app_graphql_request_duration_seconds`    | Histogram | Request latency buckets               |
| `app_server_load_percent`                 | Gauge     | Simulated CPU load (0–100)            |
| `app_active_requests`                     | Gauge     | In-flight requests right now          |

Useful PromQL queries:

```promql
# Request rate per server (last 30 s)
rate(app_graphql_requests_total[30s])

# P95 latency per server
histogram_quantile(0.95,
  sum by(instance, le) (rate(app_graphql_request_duration_seconds_bucket[1m])))

# Which server is hottest right now?
topk(1, app_server_load_percent)
```

---

## Grafana Dashboard

The dashboard is **auto-provisioned** — no manual import needed.

Panels included:

1. **Requests/s by Server** — time series, colour-coded per instance
2. **Server Load %** — simulated CPU, with yellow/red thresholds
3. **P50 / P95 Latency** — per server
4. **Active In-Flight Requests** — bar chart
5. **Requests by Query Type** — pie of traffic mix
6. **Per-server Gauges** — four speedometer dials (one per server)
7. **Summary Stats** — total requests, avg latency, max load, active connections

---

## Simulated Load Behaviour

Each server runs a background thread that randomly walks its `load` value
(0–100 %). Every few seconds there is a small chance of:

- A **load spike** (+25–45 %) — simulates a sudden batch job or GC pause
- A **relief drop** (−15–30 %) — simulates the spike ending

Heavier queries (`computeHeavy`) sleep proportionally longer on high-load
servers, so the load balancer's routing decisions become visibly meaningful.

---

## Stopping / Cleaning Up

```bash
# Stop all services
docker compose down

# Also remove volumes (Prometheus + Grafana data)
docker compose down -v
```

---

## Project Structure

```
auto-throttling-network/
├── docker-compose.yml
├── nginx/
│   └── nginx.conf            # Least-conn upstream config
├── server/
│   ├── main.py               # FastAPI + Strawberry + Prometheus
│   ├── requirements.txt
│   └── Dockerfile
├── client/
│   ├── client.py             # Async traffic generator
│   ├── requirements.txt
│   └── Dockerfile
├── prometheus/
│   └── prometheus.yml        # Scrape all 4 servers every 5 s
└── grafana/
    └── provisioning/
        ├── datasources/
        │   └── prometheus.yml
        └── dashboards/
            ├── dashboards.yml
            └── nginx-lb-demo.json   # Pre-built dashboard
```
