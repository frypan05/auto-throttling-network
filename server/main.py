import os
import time
import random
import threading
from typing import List, Optional

import strawberry
import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from strawberry.fastapi import GraphQLRouter

# ─── Config ───────────────────────────────────────────────────────────────────
SERVER_ID = os.getenv("SERVER_ID", "server-1")
START_TIME = time.time()

# ─── Prometheus Metrics ───────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "app_graphql_requests_total",
    "Total GraphQL requests",
    ["server_id", "query_name"],
)
REQUEST_LATENCY = Histogram(
    "app_graphql_request_duration_seconds",
    "GraphQL request duration in seconds",
    ["server_id", "query_name"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
SERVER_LOAD = Gauge(
    "app_server_load_percent",
    "Simulated server CPU load (0–100)",
    ["server_id"],
)
ACTIVE_REQUESTS = Gauge(
    "app_active_requests",
    "In-flight requests being handled",
    ["server_id"],
)

# ─── Load Simulation ──────────────────────────────────────────────────────────
_load = 20.0
_lock = threading.Lock()


def _load_simulator():
    """Randomly walk server load; occasional spikes to simulate hot servers."""
    global _load
    while True:
        with _lock:
            if random.random() < 0.08:           # 8 % chance of a load spike
                _load = min(95.0, _load + random.uniform(25, 45))
            elif random.random() < 0.12:         # 12 % chance of sudden relief
                _load = max(5.0, _load - random.uniform(15, 30))
            else:
                _load = max(5.0, min(92.0, _load + random.gauss(0, 6)))
            SERVER_LOAD.labels(server_id=SERVER_ID).set(_load)
        time.sleep(random.uniform(2, 6))


threading.Thread(target=_load_simulator, daemon=True).start()


def current_load() -> float:
    with _lock:
        return round(_load, 2)


def simulate_work(base: float = 0.05):
    """Sleep for a duration that grows with server load."""
    load_factor = 1 + (current_load() / 100) * 4
    time.sleep(base * load_factor + random.uniform(0, base * 0.5))


# ─── GraphQL Schema ───────────────────────────────────────────────────────────
@strawberry.type
class ServerInfo:
    server_id: str
    load: float
    uptime: float
    message: str


@strawberry.type
class Product:
    id: int
    name: str
    price: float
    category: str
    in_stock: bool


@strawberry.type
class User:
    id: int
    name: str
    email: str
    role: str


@strawberry.type
class ComputeResult:
    value: float
    iterations: int
    elapsed_ms: float
    server_id: str


@strawberry.type
class Order:
    order_id: str
    user_id: int
    total: float
    items: int
    status: str


# ─── Decorator for automatic metrics ─────────────────────────────────────────
def tracked(query_name: str):
    """Context manager that records count, latency, and active requests."""

    class _Ctx:
        def __enter__(self):
            REQUEST_COUNT.labels(server_id=SERVER_ID, query_name=query_name).inc()
            ACTIVE_REQUESTS.labels(server_id=SERVER_ID).inc()
            self._start = time.time()
            return self

        def __exit__(self, *_):
            REQUEST_LATENCY.labels(
                server_id=SERVER_ID, query_name=query_name
            ).observe(time.time() - self._start)
            ACTIVE_REQUESTS.labels(server_id=SERVER_ID).dec()

    return _Ctx()


# ─── Resolvers ────────────────────────────────────────────────────────────────
@strawberry.type
class Query:
    @strawberry.field
    def server_info(self) -> ServerInfo:
        with tracked("server_info"):
            return ServerInfo(
                server_id=SERVER_ID,
                load=current_load(),
                uptime=round(time.time() - START_TIME, 1),
                message=f"Hello from {SERVER_ID} 👋",
            )

    @strawberry.field
    def get_products(
        self,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> List[Product]:
        with tracked("get_products"):
            simulate_work(0.03)
            cats = ["electronics", "books", "clothing", "sports", "home"]
            products = [
                Product(
                    id=i,
                    name=f"Product-{i}",
                    price=round(random.uniform(5, 999), 2),
                    category=random.choice(cats),
                    in_stock=random.random() > 0.2,
                )
                for i in range(1, 51)
            ]
            if category:
                products = [p for p in products if p.category == category]
            return products[:limit]

    @strawberry.field
    def get_users(self, limit: int = 10) -> List[User]:
        with tracked("get_users"):
            simulate_work(0.02)
            roles = ["admin", "editor", "viewer", "moderator"]
            return [
                User(
                    id=i,
                    name=f"User-{i}",
                    email=f"user{i}@demo.local",
                    role=random.choice(roles),
                )
                for i in range(1, min(limit, 50) + 1)
            ]

    @strawberry.field
    def compute_heavy(self, iterations: int = 5000) -> ComputeResult:
        with tracked("compute_heavy"):
            n = min(iterations, 50_000)
            simulate_work(0.15)          # heavier base delay
            t0 = time.perf_counter()
            value = float(sum(i * i for i in range(n)))
            elapsed_ms = (time.perf_counter() - t0) * 1_000
            return ComputeResult(
                value=value,
                iterations=n,
                elapsed_ms=round(elapsed_ms, 2),
                server_id=SERVER_ID,
            )

    @strawberry.field
    def get_orders(
        self, user_id: Optional[int] = None, limit: int = 5
    ) -> List[Order]:
        with tracked("get_orders"):
            simulate_work(0.04)
            statuses = ["pending", "processing", "shipped", "delivered", "cancelled"]
            return [
                Order(
                    order_id=f"ORD-{random.randint(10_000, 99_999)}",
                    user_id=user_id or random.randint(1, 100),
                    total=round(random.uniform(20, 2_000), 2),
                    items=random.randint(1, 10),
                    status=random.choice(statuses),
                )
                for _ in range(limit)
            ]


# ─── App ──────────────────────────────────────────────────────────────────────
schema = strawberry.Schema(query=Query)
graphql_router = GraphQLRouter(schema, graphiql=True)

app = FastAPI(title=f"GraphQL Backend — {SERVER_ID}")
app.include_router(graphql_router, prefix="/graphql")


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health():
    return {"status": "ok", "server_id": SERVER_ID, "load": current_load()}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
