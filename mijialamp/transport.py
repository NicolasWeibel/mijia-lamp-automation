from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LampPhysicalState:
    power: str | None
    brightness: int | None
    kelvin: int | None
    ip: str
    model: str | None = None
    device_id: str | None = None


@dataclass(frozen=True)
class ProfileValues:
    name: str
    kelvin: int
    brightness: int


@runtime_checkable
class LampTransport(Protocol):
    def probe_identity(self, ip: str, timeout: float | None = None) -> tuple[str, str]: ...

    def read_state(self, ip: str, timeout: float | None = None) -> LampPhysicalState: ...

    def set_power(self, power: str, *, ip: str | None = None, fast: bool = False) -> None: ...

    def set_power_critical_off(self, *, ip: str | None = None, timeout: float = 0.25) -> None: ...

    def apply_profile(self, profile: ProfileValues, *, ip: str | None = None, fast: bool = False) -> None: ...

    def discover(self, *, force: bool = False) -> str | None: ...

    def ensure_reachable(self, wait_seconds: float, *, allow_discovery: bool = True) -> str: ...
