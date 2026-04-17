"""
Async load-generation client.

Sends a randomised mix of GraphQL queries to Nginx.
Each query is weighted so heavy queries are less frequent.
Prints which server handled each request so you can watch
the load balancer routing live in the terminal.
"""
import asyncio
import os
import random
import time

import aiohttp

NGINX_URL = os.getenv("NGINX_URL", "http://nginx/graphql")
CONCURRENCY = int(os.getenv("CONCURRENCY", "3"))   # parallel workers
MIN_DELAY = float(os.getenv("MIN_DELAY", "0.2"))   # seconds between each worker's requests
MAX_DELAY = float(os.getenv("MAX_DELAY", "1.2"))

# ─── GraphQL query bank ───────────────────────────────────────────────────────
QUERIES = {
    "server_info": (
        3,
        """
        query ServerInfo {
          serverInfo {
            serverId
            load
            uptime
            message
          }
        }
        """,
    ),
    "get_products": (
        3,
        """
        query GetProducts {
          getProducts(limit: 8) {
            id
            name
            price
            category
            inStock
          }
        }
        """,
    ),
    "get_users": (
        3,
        """
        query GetUsers {
          getUsers(limit: 10) {
            id
            name
            email
            role
          }
        }
        """,
    ),
    "compute_heavy": (
        1,                          # low weight — expensive query
        """
        query ComputeHeavy {
          computeHeavy(iterations: 8000) {
            value
            iterations
            elapsedMs
            serverId
          }
        }
        """,
    ),
    "get_orders": (
        2,
        """
        query GetOrders {
          getOrders(limit: 4) {
            orderId
            userId
            total
            items
            status
          }
        }
        """,
    ),
}

_names = list(QUERIES.keys())
_weights = [QUERIES[n][0] for n in _names]
_query_bodies = {n: QUERIES[n][1] for n in _names}

# ANSI colours for server IDs
_COLOURS = {
    "server-1": "\033[96m",
    "server-2": "\033[92m",
    "server-3": "\033[93m",
    "server-4": "\033[95m",
}
_RESET = "\033[0m"
_RED = "\033[91m"


def _colour(server_id: str) -> str:
    return _COLOURS.get(server_id, "\033[97m")


def _extract_server(data: dict) -> str:
    """Best-effort extraction of serverId from any query result."""
    for val in (data or {}).values():
        if isinstance(val, dict) and "serverId" in val:
            return val["serverId"]
        if isinstance(val, list) and val and isinstance(val[0], dict) and "serverId" in val[0]:
            return val[0]["serverId"]
    return "?"


async def worker(worker_id: int, session: aiohttp.ClientSession):
    """Continuously fire requests; each worker has its own cadence."""
    while True:
        name = random.choices(_names, weights=_weights)[0]
        query = _query_bodies[name]
        start = time.perf_counter()

        try:
            async with session.post(
                NGINX_URL,
                json={"query": query},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                elapsed_ms = (time.perf_counter() - start) * 1_000
                body = await resp.json()

                if "errors" in body:
                    print(
                        f"{_RED}❌ [W{worker_id}] {name:<14} "
                        f"HTTP {resp.status} | {elapsed_ms:6.1f}ms | "
                        f"errors: {body['errors']}{_RESET}"
                    )
                else:
                    server_id = _extract_server(body.get("data", {}))
                    c = _colour(server_id)
                    print(
                        f"✅ [W{worker_id}] {name:<14} "
                        f"→ {c}{server_id:<10}{_RESET} | {elapsed_ms:6.1f}ms"
                    )

        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start) * 1_000
            print(f"{_RED}⏱  [W{worker_id}] {name:<14} TIMEOUT after {elapsed_ms:.0f}ms{_RESET}")
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.perf_counter() - start) * 1_000
            print(f"{_RED}💥 [W{worker_id}] {name:<14} ERROR {elapsed_ms:.0f}ms — {exc}{_RESET}")

        await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


async def wait_for_nginx(session: aiohttp.ClientSession, retries: int = 20):
    print(f"⏳  Waiting for Nginx at {NGINX_URL} …")
    for i in range(retries):
        try:
            async with session.post(
                NGINX_URL,
                json={"query": "{ serverInfo { serverId } }"},
                timeout=aiohttp.ClientTimeout(total=3),
            ) as r:
                if r.status < 500:
                    print(f"✅  Nginx ready (attempt {i + 1})\n")
                    return
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(2)
    raise RuntimeError("Nginx never became ready — aborting.")


async def main():
    print("=" * 60)
    print(f"  Nginx Load-Balancer Demo — GraphQL Client")
    print(f"  Target  : {NGINX_URL}")
    print(f"  Workers : {CONCURRENCY}")
    print(f"  Delay   : {MIN_DELAY}–{MAX_DELAY}s per worker")
    print("=" * 60)

    connector = aiohttp.TCPConnector(limit=CONCURRENCY * 2)
    async with aiohttp.ClientSession(connector=connector) as session:
        await wait_for_nginx(session)
        tasks = [asyncio.create_task(worker(i + 1, session)) for i in range(CONCURRENCY)]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
