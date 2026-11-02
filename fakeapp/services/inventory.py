from fastapi import APIRouter, HTTPException

SERVICE = "inventory"
router = APIRouter()
STOCK = {f"SKU-{i}": {"qty": 10_000, "price": 10.0 * i} for i in range(1, 6)}


@router.post("/reserve")
async def reserve(body: dict):
    item = STOCK.get(body.get("sku"))
    if item is None:
        raise HTTPException(404, "unknown sku")
    qty = int(body.get("qty", 1))
    if item["qty"] < qty:
        raise HTTPException(409, "out of stock")
    item["qty"] -= qty
    return {"sku": body["sku"], "reserved": qty, "price": item["price"]}


@router.get("/stock/{sku}")
async def stock(sku: str):
    if sku not in STOCK:
        raise HTTPException(404, "unknown sku")
    return STOCK[sku]
