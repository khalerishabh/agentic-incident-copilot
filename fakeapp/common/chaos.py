import asyncio
import random
import time
from dataclasses import dataclass, field

SUPPORTED_FAULTS = {
    "latency": {"delay_ms": 800, "probability": 1.0},
    "error_rate": {"probability": 0.3, "status": 500},
    "memory_leak": {"kb_per_request": 512},
    "cpu_burn": {"ms_per_request": 200},
}


class InjectedFailure(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


@dataclass
class ChaosState:
    active: dict[str, dict] = field(default_factory=dict)
    _leak: list[bytes] = field(default_factory=list)

    def enable(self, fault: str, params: dict | None = None) -> dict:
        if fault not in SUPPORTED_FAULTS:
            raise KeyError(fault)
        merged = {**SUPPORTED_FAULTS[fault], **(params or {})}
        self.active[fault] = merged
        return merged

    def disable(self, fault: str) -> None:
        self.active.pop(fault, None)
        if fault == "memory_leak":
            self._leak.clear()

    async def before_request(self) -> None:
        lat = self.active.get("latency")
        if lat and random.random() < lat["probability"]:
            await asyncio.sleep(lat["delay_ms"] / 1000)

        cpu = self.active.get("cpu_burn")
        if cpu:
            end = time.perf_counter() + cpu["ms_per_request"] / 1000
            while time.perf_counter() < end:
                pass

        leak = self.active.get("memory_leak")
        if leak:
            self._leak.append(bytes(leak["kb_per_request"] * 1024))

        err = self.active.get("error_rate")
        if err and random.random() < err["probability"]:
            raise InjectedFailure(err["status"], "internal processing error")


chaos = ChaosState()
