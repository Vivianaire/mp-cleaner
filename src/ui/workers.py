"""后台 QThread worker:把阻塞的 adb 调用挪出 UI 主线程。

扫描/清理这种长任务必须经此;短查询(设备枚举)也走 worker 以免首次启动 adb
server 时的短暂卡顿。
"""
from __future__ import annotations

import time

from PyQt6 import QtCore

from ..adb import AdbClient, DeviceInfo, SCAN_ROOT


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
                        "storage": self._client.df(d.serial, SCAN_ROOT),
                    }
                except Exception:
                    props[d.serial] = {}
            self.result.emit(devs, props)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class ScannerWorker(_Worker):
    """流式扫描:经 ``DeviceBackend.iter_files`` 拉取,节流发射 batchReady。

    记录为 ``(abs_path, size, is_file, mtime)``。trie/model 在主线程按批增量构建。
    """

    batchReady = QtCore.pyqtSignal(list)                # list[(path, size, is_file, mtime)]
    progress = QtCore.pyqtSignal(int, object)           # files, bytes(bytes 用 object 防 int32 溢出)
    packagesReady = QtCore.pyqtSignal(list)             # 已装包名(分类用)
    finishedScan = QtCore.pyqtSignal(int, int, object)  # files, dirs, bytes

    _BATCH = 4000
    _INTERVAL = 0.05

    def __init__(self, backend, root: str = SCAN_ROOT, maxdepth: int | None = None, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._root = root
        self._maxdepth = maxdepth
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        files = dirs = nbytes = 0
        try:
            batch: list = []
            last = time.monotonic()
            for rec in self._backend.iter_files(self._root, self._maxdepth):
                if self._cancel:
                    break
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
            try:
                self.packagesReady.emit(self._backend.installed_packages())
            except Exception:  # noqa: BLE001
                self.packagesReady.emit([])
            self.progress.emit(files, nbytes)
            self.finishedScan.emit(files, dirs, nbytes)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class CacheWorker(_Worker):
    """后台判定缓存命中:目录签名一致则由 SQLite 快照重建 trie(大快照重建不卡 UI)。"""

    result = QtCore.pyqtSignal(object, bool)   # (trie_or_None, hit)

    def __init__(self, scan_service, root: str, parent=None):
        super().__init__(parent)
        self._service = scan_service
        self._root = root

    def run(self) -> None:
        try:
            trie = self._service.try_cached(self._root)
            self.result.emit(trie, trie is not None)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


def _shell_quote(p: str) -> str:
    """单引号包裹路径,转义内嵌单引号。"""
    return "'" + p.replace("'", "'\\''") + "'"


def _is_safe_path(p: str, root: str) -> bool:
    r = root.rstrip("/")
    if not p.startswith(r + "/"):
        return False
    if p == r:
        return False
    if ".." in p.split("/"):
        return False
    return True


class CleanToTrashWorker(_Worker):
    """默认安全清理:受保护项跳过,安全项 ``mv`` 入回收站(可恢复)。"""

    progress = QtCore.pyqtSignal(int, int, str)         # done, total, path
    result = QtCore.pyqtSignal(int, int, int, object)   # moved, skipped, failed, freed

    def __init__(self, backend, store, items, root, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._store = store
        self._items = items
        self._root = root

    def run(self) -> None:
        from ..cleaner import mark_protected
        from ..services import trash_service

        moved = skipped = failed = 0
        freed = 0
        try:
            try:
                protected = self._backend.foreground_packages()
            except Exception:  # noqa: BLE001
                protected = set()
            mark_protected(self._items, protected)

            todo = [
                it for it in self._items
                if not it.protected and _is_safe_path(it.path, self._root)
            ]
            skipped = len(self._items) - len(todo)
            total = len(todo)
            for i, it in enumerate(todo, 1):
                self.progress.emit(i, total, it.path)
                try:
                    trash_service.move_to_trash(self._backend, self._store, it)
                    moved += 1
                    freed += it.size
                except Exception:  # noqa: BLE001
                    failed += 1
            self.result.emit(moved, skipped, failed, freed)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class PhoneTrashWorker(_Worker):
    """检测 / 清空手机自带回收站。op='detect'|'empty'(empty 时带 target)。"""

    detected = QtCore.pyqtSignal(list)                  # detect 结果
    emptied = QtCore.pyqtSignal(int)                    # empty 释放字节

    def __init__(self, backend, op: str, target=None, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._op = op
        self._target = target

    def run(self) -> None:
        from ..services import trash_service

        try:
            if self._op == "detect":
                self.detected.emit(trash_service.detect_phone_trash(self._backend))
            elif self._op == "empty":
                self.emptied.emit(
                    trash_service.empty_phone_trash(self._backend, self._target)
                )
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


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

