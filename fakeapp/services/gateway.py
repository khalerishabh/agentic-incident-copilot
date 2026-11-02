import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fakeapp.common.app_factory import call_upstream

SERVICE = "gateway"
ORDERS = os.getenv("ORDERS_URL", "http://orders:8000")
router = APIRouter()


@router.post("/api/orders")
async def create_order(request: Request, body: dict):
    resp = await call_upstream(request, "POST", f"{ORDERS}/orders", "orders", SERVICE, json=body)
    return JSONResponse(resp.json(), status_code=resp.status_code)


@router.get("/api/orders/{order_id}")
async def get_order(request: Request, order_id: str):
    resp = await call_upstream(request, "GET", f"{ORDERS}/orders/{order_id}", "orders", SERVICE)
    return JSONResponse(resp.json(), status_code=resp.status_code)
