import asyncio
import os
import random

import httpx

GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:8000")
RPS = float(os.getenv("LOADGEN_RPS", "5"))


async def one(client: httpx.AsyncClient) -> None:
    try:
        await client.post(f"{GATEWAY}/api/orders",
                          json={"sku": f"SKU-{random.randint(1, 5)}", "qty": random.randint(1, 3)})
    except httpx.HTTPError:
        pass


async def main() -> None:
    await asyncio.sleep(5)
    async with httpx.AsyncClient(timeout=5.0) as client:
        while True:
            asyncio.create_task(one(client))
            await asyncio.sleep(1 / RPS)


if __name__ == "__main__":
    asyncio.run(main())
