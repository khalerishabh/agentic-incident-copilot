import argparse
import os

import httpx

PORTS = {"gateway": 8000, "orders": 8001, "payments": 8002, "inventory": 8003}


def main() -> None:
    p = argparse.ArgumentParser(description="Toggle faults on the fake microservices")
    p.add_argument("action", choices=["enable", "disable", "status"])
    p.add_argument("service", choices=list(PORTS))
    p.add_argument("fault", nargs="?")
    p.add_argument("--param", action="append", default=[], help="key=value")
    args = p.parse_args()

    base = f"http://localhost:{PORTS[args.service]}"
    headers = {"x-chaos-token": os.getenv("CHAOS_ADMIN_TOKEN", "change-me")}

    if args.action == "status":
        r = httpx.get(f"{base}/chaos", headers=headers)
    elif args.action == "enable":
        params = {k: float(v) for k, v in (kv.split("=", 1) for kv in args.param)}
        r = httpx.post(f"{base}/chaos/{args.fault}", json=params or None, headers=headers)
    else:
        r = httpx.delete(f"{base}/chaos/{args.fault}", headers=headers)
    print(r.status_code, r.json())


if __name__ == "__main__":
    main()
