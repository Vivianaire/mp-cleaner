"""设备后端抽象。

把「怎么跟设备说话」从业务逻辑里隔离出来。当前实现 ``AdbShellBackend``(uid 2000,
经 adb)。v3 增加 ``ShizukuAgentBackend``(on-device Agent ↔ Shizuku),二者实现同一
接口,业务层无感切换。

记录格式统一为 ``(path, size, is_file, mtime)``。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from ..adb import AdbClient, SCAN_ROOT, dirs_command, scan_command

Record = tuple[str, int, bool, int]


def parse_record(line: str) -> Record | None:
    """解析 ``find -printf`` 输出的一行:path|size|mode|mtime。

    rsplit 剥出 size|mode|mtime(路径中若含 '|' 也不受影响);mode 首字符判类型。
    """
    line = line.rstrip("\n")
    if not line:
        return None
    parts = line.rsplit("|", 3)
    if len(parts) != 4:
        return None
    path, size_s, mode, mtime_s = parts
    t = mode[:1]
    if t == "l":                       # 符号链接:跳过,防环
        return None
    is_file = t == "-"
    try:
        size = int(size_s)
    except ValueError:
        return None
    try:
        mtime = int(float(mtime_s))
    except ValueError:
        mtime = 0
    return (path, size, is_file, mtime)


class DeviceBackend(ABC):
    """与单个已连接设备的通信抽象。"""

    serial: str

    @abstractmethod
    def iter_files(self, root: str, maxdepth: int | None = None) -> Iterator[Record]:
        """流式产出文件元数据(阻塞生成器,需在工作线程调用)。"""

    @abstractmethod
    def list_dirs(self, root: str) -> dict[str, int]:
        """{绝对路径: mtime},仅目录(快探,用于缓存命中判定)。"""

    @abstractmethod
    def df(self, path: str) -> tuple[int, int, int] | None:
        """(total, used, available) 字节。"""

    @abstractmethod
    def installed_packages(self) -> list[str]: ...

    @abstractmethod
    def foreground_packages(self) -> set[str]: ...

    @abstractmethod
    def shell(self, command: str, timeout: float = 60) -> str: ...

    @abstractmethod
    def move(self, src: str, dst: str) -> None: ...

    @abstractmethod
    def delete(self, path: str) -> None: ...

    @abstractmethod
    def mkdir(self, path: str) -> None: ...


class AdbShellBackend(DeviceBackend):
    """经 adb shell 的实现(uid 2000,与 Shizuku 同级)。"""

    def __init__(self, client: AdbClient, serial: str):
        self.client = client
        self.serial = serial

    def shell(self, command: str, timeout: float = 60) -> str:
        return self.client.shell(self.serial, command, timeout=timeout)

    def iter_files(self, root: str, maxdepth: int | None = None) -> Iterator[Record]:
        proc = self.client.shell_popen(self.serial, scan_command(root, maxdepth))
        try:
            for line in proc.stdout:
                rec = parse_record(line)
                if rec is not None:
                    yield rec
        finally:
            # 提前中止(取消/异常)时终止子进程,避免 find 写满管道致 wait() 死锁
            if proc.poll() is None:
                proc.terminate()
            proc.wait()

    def list_dirs(self, root: str) -> dict[str, int]:
        out = self.shell(dirs_command(root), timeout=180)
        dirs: dict[str, int] = {}
        for line in out.splitlines():
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.rsplit("|", 1)
            if len(parts) != 2:
                continue
            path = parts[0]
            if path == root:          # 剔除根自身(get_dirs 用 LIKE root/% 不含根)
                continue
            try:
                dirs[path] = int(float(parts[1]))
            except ValueError:
                continue
        return dirs

    def df(self, path: str = SCAN_ROOT) -> tuple[int, int, int] | None:
        return self.client.df(self.serial, path)

    def installed_packages(self) -> list[str]:
        return self.client.installed_packages(self.serial)

    def foreground_packages(self) -> set[str]:
        from ..cleaner.lockdetect import protected_packages

        # 与已装包取交集(去 dumpsys 类名噪声)
        try:
            installed = set(self.installed_packages())
        except Exception:  # noqa: BLE001
            installed = None
        return protected_packages(self.client, self.serial, installed)

    def move(self, src: str, dst: str) -> None:
        self.shell(f"mv {_q(src)} {_q(dst)}", timeout=180)

    def delete(self, path: str) -> None:
        self.shell(f"rm -rf {_q(path)}", timeout=180)

    def mkdir(self, path: str) -> None:
        self.shell(f"mkdir -p {_q(path)}", timeout=60)


def _q(p: str) -> str:
    """单引号包裹路径,转义内嵌单引号。"""
    return "'" + p.replace("'", "'\\''") + "'"
