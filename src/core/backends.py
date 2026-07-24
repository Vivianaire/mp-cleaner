"""设备后端抽象。

把「怎么跟设备说话」从业务逻辑里隔离出来。当前实现 ``AdbShellBackend``(uid 2000,
经 adb)。深度分析(diskstats/usagestats/force-stop/采样哈希)全部走 adb shell 的
既有权限,不依赖 Shizuku/Root/装 APK;后端接口保留以便将来平替。

记录格式统一为 ``(path, size, is_file, mtime)``。
"""
from __future__ import annotations

import queue
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from typing import Iterator

from ..adb import AdbClient, SCAN_ROOT, dirs_command, scan_command

Record = tuple[str, int, bool, int]

# reader 线程结束哨兵(放入队列,主生成器据此判 EOF)
_SENTINEL: object = object()


class ScanStalled(Exception):
    """流式扫描看门狗触发:相邻两行间隔超过 stall_timeout,判定 adb 连接停滞。"""


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
    def iter_files(
        self,
        root: str,
        maxdepth: int | None = None,
        *,
        stall_timeout: float | None = None,
        cancel_event: threading.Event | None = None,
        poll_interval: float = 0.5,
    ) -> Iterator[Record]:
        """流式产出文件元数据(阻塞生成器,需在工作线程调用)。

        stall_timeout:相邻两行最大允许间隔秒数;超时由实现决定如何上报
            (AdbShellBackend 会 raise ScanStalled)。None 表示不启用看门狗。
        cancel_event:外部 set() 即可提前中止;None 表示不可取消。
        poll_interval:看门狗/取消的轮询粒度。
        """

    @abstractmethod
    def list_dirs(self, root: str) -> dict[str, int]:
        """{绝对路径: mtime},仅目录(快探,用于缓存命中判定)。"""

    @abstractmethod
    def df(self, path: str) -> tuple[int, int, int] | None:
        """(total, used, available) 字节。"""

    @abstractmethod
    def installed_packages(self) -> list[str]: ...

    def third_party_packages(self) -> list[str]:
        """第三方(用户安装)包名;默认回退到全量已装包。"""
        return self.installed_packages()

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

    # --- 深度分析(可选,advisory;默认空实现,不强制后端支持)---
    def disk_stats(self) -> dict[str, dict[str, int]]:
        """{pkg: {app,data,cache,total}} 字节(权威 per-app 口径)。"""
        return {}

    def app_idle(self, pkg: str) -> bool | None:
        """应用是否处于系统闲置态(app-standby);不可判定则 None。"""
        return None

    def force_stop(self, pkg: str) -> None:
        """清数据前停应用(默认 no-op)。"""

    def sample_hashes(self, paths: list[str], nbytes: int = 131072) -> dict[str, str]:
        """{path: 采样哈希}(首尾各 nbytes 字节的 md5;用于同大小组内去重复核)。"""
        return {}


class AdbShellBackend(DeviceBackend):
    """经 adb shell 的实现(uid 2000,与 Shizuku 同级)。"""

    def __init__(self, client: AdbClient, serial: str):
        self.client = client
        self.serial = serial

    def shell(self, command: str, timeout: float = 60) -> str:
        return self.client.shell(self.serial, command, timeout=timeout)

    def iter_files(
        self,
        root: str,
        maxdepth: int | None = None,
        *,
        stall_timeout: float | None = None,
        cancel_event: threading.Event | None = None,
        poll_interval: float = 0.5,
        queue_maxsize: int = 1024,
    ) -> Iterator[Record]:
        """流式产出文件元数据(阻塞生成器,需在工作线程调用)。

        看门狗机制:独立 daemon 线程阻塞读 ``proc.stdout`` 入有界 Queue(提供背压);
        本生成器用 ``q.get(timeout=poll_interval)`` 短轮询,每轮检查:
          - cancel_event 已 set → 正常返回(用户取消);
          - 距上一条记录 > stall_timeout(且已收到过首条)→ raise ScanStalled;
          - 收到哨兵 → 正常 EOF。
        finally 里 terminate→wait→kill→wait、关 stdout、join reader,保证不泄漏
        进程/线程、不死锁。stall_timeout=None 时不启用看门狗(等价旧行为)。
        """
        if cancel_event is None:
            cancel_event = threading.Event()
        proc = self.client.shell_popen(self.serial, scan_command(root, maxdepth))
        q: "queue.Queue[object]" = queue.Queue(maxsize=queue_maxsize)

        def _reader() -> None:
            # 阻塞读 stdout;任何异常都不让 reader 卡死,最终都发哨兵
            try:
                for line in proc.stdout:
                    q.put(line)            # 队列满时阻塞,提供背压
            except Exception:  # noqa: BLE001
                pass
            finally:
                try:
                    q.put(_SENTINEL)
                except Exception:  # noqa: BLE001
                    pass

        reader = threading.Thread(
            target=_reader, name="adb-stdout-reader", daemon=True
        )
        reader.start()

        last_progress: float | None = None   # 收到第一条记录后才武装看门狗
        try:
            while True:
                if cancel_event.is_set():
                    return                    # 用户取消:正常返回(不抛)

                try:
                    item = q.get(timeout=poll_interval)
                except queue.Empty:
                    # 进程已退出 + 队列空 + reader 已结束:哨兵丢失兜底
                    if not reader.is_alive() and q.empty() and proc.poll() is not None:
                        return
                    # 看门狗(只在已开始接收数据后武装)
                    if (
                        stall_timeout is not None
                        and last_progress is not None
                        and time.monotonic() - last_progress > stall_timeout
                    ):
                        raise ScanStalled(
                            f"adb 流式扫描停滞超时({stall_timeout}s 无新数据)"
                        )
                    continue

                if item is _SENTINEL:
                    return                    # 正常 EOF

                last_progress = time.monotonic()
                rec = parse_record(item)  # type: ignore[arg-type]
                if rec is not None:
                    yield rec
        finally:
            # 1) set cancel_event(语义无害)+ terminate 子进程:adb.exe 被杀 →
            #    设备端 stdout 关闭 → reader 的 for-line 收到 EOF 自然退出
            cancel_event.set()
            # 2) 终止子进程:terminate → 等 2s → 仍活则 kill → 等 2s
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try:
                            proc.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            pass
                else:
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
            except Exception:  # noqa: BLE001
                pass
            # 3) 关 stdout 读端,兜底打破 reader 可能的阻塞读
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:  # noqa: BLE001
                pass
            # 4) join reader;daemon=True 保证即便 join 不上也不阻止退出
            reader.join(timeout=5)

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

    def third_party_packages(self) -> list[str]:
        return self.client.third_party_packages(self.serial)

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

    # --- 深度分析 ---
    def disk_stats(self) -> dict[str, dict[str, int]]:
        return self.client.disk_stats(self.serial)

    def app_idle(self, pkg: str) -> bool | None:
        return self.client.app_idle(self.serial, pkg)

    def force_stop(self, pkg: str) -> None:
        self.client.force_stop(self.serial, pkg)

    def sample_hashes(self, paths: list[str], nbytes: int = 131072) -> dict[str, str]:
        """分批跑设备端 shell 循环:各文件取首尾 nbytes 字节算 md5。

        仅对「同大小候选组」调用(数量已很小),故每文件一次 head+tail 采样即可
        区分内容;单次 shell 处理一批(限长 80 条)以摊薄 adb 往返开销。
        """
        result: dict[str, str] = {}
        for i in range(0, len(paths), 80):
            chunk = paths[i : i + 80]
            args = " ".join(_q(p) for p in chunk)
            script = (
                f"for p in {args}; do "
                f'h=$( {{ head -c {nbytes} "$p"; tail -c {nbytes} "$p"; }} '
                f"2>/dev/null | md5sum 2>/dev/null | cut -d' ' -f1 ); "
                f'echo "$h|$p"; done'
            )
            try:
                out = self.shell(script, timeout=120)
            except Exception:  # noqa: BLE001
                continue
            for line in out.splitlines():
                line = line.rstrip("\n")
                if "|" not in line:
                    continue
                h, path = line.split("|", 1)
                h = h.strip()
                if h:
                    result[path] = h
        return result


def _q(p: str) -> str:
    """单引号包裹路径,转义内嵌单引号。"""
    return "'" + p.replace("'", "'\\''") + "'"
