import uuid

from fastapi import APIRouter

SERVICE = "payments"
router = APIRouter()


@router.post("/charge")
async def charge(body: dict):
    return {"id": uuid.uuid4().hex[:12], "amount": body.get("amount", 0), "status": "captured"}
