import os
import uuid

from fastapi import APIRouter, HTTPException, Request

from fakeapp.common.app_factory import call_upstream

SERVICE = "orders"
PAYMENTS = os.getenv("PAYMENTS_URL", "http://payments:8000")
INVENTORY = os.getenv("INVENTORY_URL", "http://inventory:8000")
router = APIRouter()
ORDERS: dict[str, dict] = {}


@router.post("/orders")
async def create_order(request: Request, body: dict):
    sku = body.get("sku", "SKU-1")
    qty = int(body.get("qty", 1))

    reserve = await call_upstream(request, "POST", f"{INVENTORY}/reserve", "inventory", SERVICE,
                                  json={"sku": sku, "qty": qty})
    if reserve.status_code != 200:
        raise HTTPException(reserve.status_code, "reservation failed")

    charge = await call_upstream(request, "POST", f"{PAYMENTS}/charge", "payments", SERVICE,
                                 json={"amount": reserve.json()["price"] * qty})
    if charge.status_code != 200:
        raise HTTPException(charge.status_code, "payment failed")

    order_id = uuid.uuid4().hex[:10]
    ORDERS[order_id] = {"id": order_id, "sku": sku, "qty": qty, "payment": charge.json()["id"]}
    return ORDERS[order_id]


@router.get("/orders/{order_id}")
async def get_order(order_id: str):
    if order_id not in ORDERS:
        raise HTTPException(404, "order not found")
    return ORDERS[order_id]
