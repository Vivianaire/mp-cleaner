"""后台 QThread worker:把阻塞的 adb 调用挪出 UI 主线程。

扫描/清理这种长任务必须经此;短查询(设备枚举)也走 worker 以免首次启动 adb
server 时的短暂卡顿。
"""
from __future__ import annotations

import time

from PyQt6 import QtCore

from ..adb import AdbClient, DeviceInfo, SCAN_ROOT, scan_command


class _Worker(QtCore.QThread):
    """基类:统一错误信号。子类定义 ``result`` 信号并在 ``run`` 里 emit。"""

    failed = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int, str)        # (百分比, 说明) 可选


class DeviceListWorker(_Worker):
    """枚举设备 + 为已授权设备拉取厂商/型号/Android 版本。"""

    result = QtCore.pyqtSignal(list, dict)        # (list[DeviceInfo], {serial: props})

    def __init__(self, client: AdbClient, parent=None):
        super().__init__(parent)
        self._client = client

    def run(self) -> None:  # noqa: D401
        try:
            self._client.start_server()
            devs = self._client.devices()
            props: dict[str, dict[str, str]] = {}
            for d in devs:
                if not d.authorized:
                    continue
                try:
                    props[d.serial] = {
                        "brand": self._client.getprop(d.serial, "ro.product.manufacturer"),
                        "model": self._client.getprop(d.serial, "ro.product.model"),
                        "release": self._client.android_release(d.serial),
                    }
                except Exception:
                    props[d.serial] = {}
            self.result.emit(devs, props)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class ScannerWorker(_Worker):
    """流式扫描:跑 ``find -printf``,逐行解析,节流发射 batchReady。

    每条记录为 ``(abs_path, size, is_file, mtime)``。trie/model 在主线程按批增量
    构建(单线程访问,免锁)。
    """

    batchReady = QtCore.pyqtSignal(list)                # list[(path, size, is_file, mtime)]
    progress = QtCore.pyqtSignal(int, object)           # files, bytes(bytes 用 object 防 int32 溢出)
    packagesReady = QtCore.pyqtSignal(list)             # 已装第三方包名(分类用)
    finishedScan = QtCore.pyqtSignal(int, int, object)  # files, dirs, bytes

    _BATCH = 4000
    _INTERVAL = 0.05

    def __init__(
        self,
        client: AdbClient,
        serial: str,
        root: str = SCAN_ROOT,
        maxdepth: int = 6,
        parent=None,
    ):
        super().__init__(parent)
        self._client = client
        self._serial = serial
        self._cmd = scan_command(root, maxdepth)
        self._proc = None

    def cancel(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def run(self) -> None:
        files = dirs = nbytes = 0
        try:
            self._proc = self._client.shell_popen(self._serial, self._cmd)
            batch: list = []
            last = time.monotonic()
            for line in self._proc.stdout:
                rec = self._parse(line)
                if rec is None:
                    continue
                _, size, is_file, _ = rec
                batch.append(rec)
                if is_file:
                    files += 1
                    nbytes += size
                else:
                    dirs += 1
                if len(batch) >= self._BATCH or time.monotonic() - last >= self._INTERVAL:
                    self.batchReady.emit(batch)
                    self.progress.emit(files, nbytes)
                    batch = []
                    last = time.monotonic()
            if batch:
                self.batchReady.emit(batch)
            self._proc.wait()
            # 拉取全量已装包(含系统应用,识别已卸载残留用)
            try:
                self.packagesReady.emit(self._client.installed_packages(self._serial))
            except Exception:
                self.packagesReady.emit([])
            self.progress.emit(files, nbytes)
            self.finishedScan.emit(files, dirs, nbytes)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))

    @staticmethod
    def _parse(line: str):
        # rsplit 剥出 size|mode|mtime(路径中若含 '|' 也不受影响)
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


def _shell_quote(p: str) -> str:
    """单引号包裹路径,转义内嵌单引号。"""
    return "'" + p.replace("'", "'\\''") + "'"


class CleanerWorker(_Worker):
    """安全清理:先做前台/运行中应用保护,再逐项 ``rm -rf``。

    安全护栏:路径必须在扫描根之下、不得为根自身、不得含 ``..``。受保护项与
    不安全项计入 skipped,不删除。
    """

    progress = QtCore.pyqtSignal(int, int, str)         # done, total, path
    result = QtCore.pyqtSignal(int, int, int, object)   # deleted, skipped, failed, freed_bytes

    def __init__(self, client, serial, items, root, installed=None, parent=None):
        super().__init__(parent)
        self._client = client
        self._serial = serial
        self._items = items
        self._root = root.rstrip("/")
        self._installed = set(installed) if installed else None

    def _safe(self, p: str) -> bool:
        if not p.startswith(self._root + "/"):
            return False
        if p == self._root:
            return False
        if ".." in p.split("/"):
            return False
        return True

    def run(self) -> None:
        from ..cleaner import mark_protected, protected_packages

        deleted = skipped = failed = 0
        freed = 0
        try:
            try:
                protected = protected_packages(
                    self._client, self._serial, self._installed
                )
            except Exception:  # noqa: BLE001
                protected = set()
            mark_protected(self._items, protected)

            todo = []
            for it in self._items:
                if it.protected or not self._safe(it.path):
                    skipped += 1
                    continue
                todo.append(it)

            total = len(todo)
            for i, it in enumerate(todo, 1):
                self.progress.emit(i, total, it.path)
                try:
                    self._client.shell(
                        self._serial, f"rm -rf {_shell_quote(it.path)}", timeout=180
                    )
                    deleted += 1
                    freed += it.size
                except Exception:  # noqa: BLE001
                    failed += 1
            self.result.emit(deleted, skipped, failed, freed)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))

