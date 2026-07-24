"""ADB 客户端:定位 adb.exe、设备枚举、one-shot shell、流式 shell。

所有方法都是**阻塞**的(subprocess)。UI 侧应通过 ``src.ui.workers`` 里的
QThread 封装调用,避免冻结主线程。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .paths import adb_path


class AdbError(RuntimeError):
    """ADB 调用失败。"""


@dataclass(frozen=True)
class DeviceInfo:
    """一台连接的设备。"""

    serial: str
    state: str                                   # "device" | "unauthorized" | "offline"
    product: str = ""
    model: str = ""
    device: str = ""
    transport_id: str = ""

    @property
    def authorized(self) -> bool:
        return self.state == "device"


class AdbClient:
    """对 adb.exe 的薄封装。"""

    def __init__(self, adb_exe: Path | str | None = None):
        self.adb_exe = str(adb_exe) if adb_exe else adb_path()

    # --- 底层 ---
    def _run(self, args: list[str], timeout: float = 30) -> str:
        cmd = [self.adb_exe, *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except FileNotFoundError as e:
            raise AdbError(f"找不到 adb 可执行文件:{self.adb_exe}") from e
        except subprocess.TimeoutExpired as e:
            raise AdbError(f"adb 命令超时:{' '.join(args)}") from e
        return proc.stdout

    def start_server(self) -> None:
        try:
            self._run(["start-server"], timeout=15)
        except AdbError:
            # 服务器可能已在运行,忽略启动错误
            pass

    # --- 设备枚举 ---
    def devices(self) -> list[DeviceInfo]:
        """解析 ``adb devices -l``。"""
        out = self._run(["devices", "-l"], timeout=15)
        infos: list[DeviceInfo] = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            kw: dict[str, str] = {}
            for p in parts[2:]:
                if ":" in p:
                    k, v = p.split(":", 1)
                    kw[k] = v
            infos.append(
                DeviceInfo(
                    serial=serial,
                    state=state,
                    product=kw.get("product", ""),
                    model=kw.get("model", ""),
                    device=kw.get("device", ""),
                    transport_id=kw.get("transport_id", ""),
                )
            )
        return infos

    # --- shell ---
    def shell(self, serial: str, command: str, timeout: float = 60) -> str:
        """one-shot:``adb -s <serial> shell "<command>"``,返回 stdout。"""
        return self._run(["-s", serial, "shell", command], timeout=timeout)

    def shell_popen(self, serial: str, command: str) -> subprocess.Popen:
        """流式 shell:返回 Popen,逐行读 stdout(扫描用)。

        调用方负责读取 stdout 并最终 ``wait()``/回收进程。
        """
        cmd = [self.adb_exe, "-s", serial, "shell", command]
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

    # --- 便捷属性 ---
    def getprop(self, serial: str, name: str) -> str:
        return self.shell(serial, f"getprop {name}").strip()

    def android_release(self, serial: str) -> str:
        return self.getprop(serial, "ro.build.version.release")

    def _packages(self, serial: str, args: str) -> list[str]:
        out = self.shell(serial, f"pm list packages {args}".strip(), timeout=30)
        pkgs = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                pkgs.append(line[len("package:"):])
        return pkgs

    def installed_packages(self, serial: str) -> list[str]:
        """全量已装包(含系统应用)——识别「已卸载残留」用。

        注意:报告原用 ``-3``(仅第三方)判残留,会把所有系统应用
        (com.oplus.* / com.android.* …)误判为残留,故改用全量列表。
        """
        return self._packages(serial, "")

    def third_party_packages(self, serial: str) -> list[str]:
        return self._packages(serial, "-3")

    def df(self, serial: str, path: str) -> tuple[int, int, int] | None:
        """``df -k <path>`` -> (total, used, available) 字节数;失败返回 None。"""
        out = self.shell(serial, f"df -k {path}", timeout=15)
        for line in out.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("filesystem"):
                continue
            parts = line.split()
            # [/dev/fuse, 1K-blocks, used, avail, use%, mount]
            if len(parts) >= 4:
                try:
                    total = int(parts[1]) * 1024
                    used = int(parts[2]) * 1024
                    avail = int(parts[3]) * 1024
                    return (total, used, avail)
                except ValueError:
                    continue
        return None
