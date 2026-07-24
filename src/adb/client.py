"""ADB 客户端:定位 adb.exe、设备枚举、one-shot shell、流式 shell。

所有方法都是**阻塞**的(subprocess)。UI 侧应通过 ``src.ui.workers`` 里的
QThread 封装调用,避免冻结主线程。
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .paths import adb_path

# Windows 下隐藏 adb 子进程的控制台黑窗。pythonw 调控制台子系统程序(adb.exe)
# 时,系统会为其分配新控制台 → 每次 adb 调用弹一个 cmd 黑窗。CREATE_NO_WINDOW
# 抑制之;非 Windows 平台为 0(标志不存在)。
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# dumpsys diskstats 尾部的数组行:``Label: [ ... ]``
_ARR_RE = re.compile(r"^\s*([A-Za-z ]+?)\s*:\s*\[(.*)\]\s*$")


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
                creationflags=_NO_WINDOW,
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
            stderr=subprocess.DEVNULL,   # 不读 stderr:避免缓冲满反压阻塞 adb
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_NO_WINDOW,
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

    # --- 深度分析(纯 adb shell,uid 2000)---
    def disk_stats(self, serial: str) -> dict[str, dict[str, int]]:
        """``dumpsys diskstats`` -> {pkg: {app,data,cache,total}}(字节)。

        权威口径:来自 PackageManager,含 ``/data/data/<pkg>`` 私有数据(全盘 find
        看不到)。尾部四个等长数组按下标对齐:Package Names / App Sizes /
        App Data Sizes / (App )?Cache Sizes。设备不支持/解析失败则返回 {}。
        """
        try:
            out = self.shell(serial, "dumpsys diskstats", timeout=30)
        except AdbError:
            return {}
        arrays: dict[str, list[str]] = {}
        for line in out.splitlines():
            m = _ARR_RE.match(line)
            if not m:
                continue
            label = m.group(1).strip().lower()
            body = m.group(2).strip()
            arrays[label] = _split_arr(body)
        names = [_unquote(x) for x in arrays.get("package names", [])]
        if not names:
            return {}
        app = _ints(arrays.get("app sizes", []))
        data = _ints(arrays.get("app data sizes", []))
        cache = _ints(arrays.get("cache sizes") or arrays.get("app cache sizes", []))
        result: dict[str, dict[str, int]] = {}
        for i, pkg in enumerate(names):
            a = app[i] if i < len(app) else 0
            d = data[i] if i < len(data) else 0
            c = cache[i] if i < len(cache) else 0
            result[pkg] = {"app": a, "data": d, "cache": c, "total": a + d}
        return result

    def app_idle(self, serial: str, pkg: str) -> bool | None:
        """``am get-inactive <pkg>`` -> True/False(闲置/活跃),不可判定则 None。

        Android app-standby 的分类信号:Idle=true 表示系统已判定长期未用。
        """
        try:
            out = self.shell(serial, f"am get-inactive {pkg}", timeout=10)
        except AdbError:
            return None
        low = out.lower()
        if "idle=true" in low:
            return True
        if "idle=false" in low:
            return False
        return None

    def force_stop(self, serial: str, pkg: str) -> None:
        """``am force-stop <pkg>``:清其数据前先停应用,避免运行中写入损坏。"""
        try:
            self.shell(serial, f"am force-stop {pkg}", timeout=15)
        except AdbError:
            pass


def _split_arr(body: str) -> list[str]:
    """拆 diskstats 数组体:按逗号分,兼顾带引号的包名(逗号不会出现在名内)。"""
    body = body.strip()
    if not body:
        return []
    return [x.strip() for x in body.split(",")]


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    return s


def _ints(items: list[str]) -> list[int]:
    out: list[int] = []
    for x in items:
        try:
            out.append(int(x.strip()))
        except ValueError:
            out.append(0)
    return out
