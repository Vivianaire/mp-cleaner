"""设备信息服务:存储容量、已装包、前台应用( thin wrapper over backend)。"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.backends import DeviceBackend


@dataclass(frozen=True)
class StorageInfo:
    total: int
    used: int
    available: int

    @property
    def use_percent(self) -> float:
        return (self.used / self.total * 100) if self.total else 0.0


class DeviceService:
    def __init__(self, backend: DeviceBackend):
        self.backend = backend

    def storage(self, path: str) -> StorageInfo | None:
        t = self.backend.df(path)
        if not t:
            return None
        return StorageInfo(*t)

    def installed_packages(self) -> list[str]:
        return self.backend.installed_packages()

    def foreground_packages(self) -> set[str]:
        return self.backend.foreground_packages()
