"""后台 QThread worker:把阻塞的 adb 调用挪出 UI 主线程。

扫描/清理这种长任务必须经此;短查询(设备枚举)也走 worker 以免首次启动 adb
server 时的短暂卡顿。
"""
from __future__ import annotations

import threading
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
    支持即时取消(cancel_event)与连接停滞看门狗(stall_timeout → status="stalled")。
    """

    batchReady = QtCore.pyqtSignal(list)                     # list[(path, size, is_file, mtime)]
    progress = QtCore.pyqtSignal(int, object)                # files, bytes(object 防 int32 溢出)
    packagesReady = QtCore.pyqtSignal(list)                  # 已装包名(分类用)
    finishedScan = QtCore.pyqtSignal(int, int, object, str)  # files, dirs, bytes, status
    # status ∈ {"ok":正常完成, "canceled":用户取消, "stalled":连接停滞超时}
    # canceled/stalled 也走本信号(不走 failed),保留已扫部分供 UI 展示。

    _BATCH = 4000
    _INTERVAL = 0.05

    def __init__(
        self,
        backend,
        root: str = SCAN_ROOT,
        maxdepth: int | None = None,
        *,
        stall_timeout: float = 60.0,
        parent=None,
    ):
        super().__init__(parent)
        self._backend = backend
        self._root = root
        self._maxdepth = maxdepth
        self._stall_timeout = stall_timeout
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        # set 事件:iter_files 的 q.get(timeout=poll_interval) 会在 ≤0.5s 内看到并 return
        self._cancel_event.set()

    def run(self) -> None:
        from ..core.backends import ScanStalled   # 局部导入,避免顶部循环引用风险

        files = dirs = nbytes = 0
        status = "ok"
        batch: list = []
        last = time.monotonic()
        try:
            try:
                for rec in self._backend.iter_files(
                    self._root,
                    self._maxdepth,
                    stall_timeout=self._stall_timeout,
                    cancel_event=self._cancel_event,
                ):
                    # 防御性兜底:即便 iter_files 未及时尊重 cancel_event,
                    # 下一条 yield 也会让我们立刻 break
                    if self._cancel_event.is_set():
                        status = "canceled"
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
            except ScanStalled:
                status = "stalled"

            # 三态共用收尾:canceled/stalled 也要把残留 batch 推出去,
            # 否则 UI 会丢最后不到 _BATCH 条已扫记录
            if batch:
                self.batchReady.emit(batch)
            try:
                self.packagesReady.emit(self._backend.installed_packages())
            except Exception:  # noqa: BLE001
                self.packagesReady.emit([])
            self.progress.emit(files, nbytes)
            self.finishedScan.emit(files, dirs, nbytes, status)
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
        from ..cleaner.lockdetect import app_pkg_for_path
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
            stopped: set[str] = set()          # 每个应用只 force-stop 一次
            for i, it in enumerate(todo, 1):
                self.progress.emit(i, total, it.path)
                # 清应用私有数据前先停应用,避免运行中写入导致损坏
                pkg = app_pkg_for_path(it.path)
                if pkg and pkg not in stopped:
                    stopped.add(pkg)
                    try:
                        self._backend.force_stop(pkg)
                    except Exception:  # noqa: BLE001
                        pass
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


class AppAnalysisWorker(_Worker):
    """深度分析:per-app 占用(diskstats)+ 闲置态(get-inactive),off-thread。"""

    result = QtCore.pyqtSignal(list)                    # list[AppUsage]

    def __init__(self, backend, top_n: int = 40, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._top_n = top_n

    def run(self) -> None:
        from ..core.appusage import analyze

        try:
            self.result.emit(analyze(self._backend, self._top_n))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class DedupWorker(_Worker):
    """重复文件复核:对「同大小候选」采样哈希,仅保留真正同内容的组。"""

    result = QtCore.pyqtSignal(list)                    # 真重复的 JunkItem 列表

    def __init__(self, backend, dup_items, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._items = dup_items

    def run(self) -> None:
        try:
            by_size: dict[int, list] = {}
            for it in self._items:
                by_size.setdefault(it.size, []).append(it)
            candidates = [it for grp in by_size.values() if len(grp) > 1 for it in grp]
            if not candidates:
                self.result.emit([])
                return
            hashes = self._backend.sample_hashes([it.path for it in candidates])
            by_key: dict[tuple, list] = {}
            for it in candidates:
                h = hashes.get(it.path)
                if not h:                     # 取不到哈希 -> 保守丢弃(不误判为重复)
                    continue
                by_key.setdefault((it.size, h), []).append(it)
            true_dups = [it for grp in by_key.values() if len(grp) > 1 for it in grp]
            self.result.emit(true_dups)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class TrashOpWorker(_Worker):
    """回收站批量操作(恢复/永久删/清空/清过期)off-thread,避免 UI 冻结。"""

    result = QtCore.pyqtSignal(str, int, object)        # op, count, freed_or_None

    def __init__(self, backend, store, op: str, tids=None, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._store = store
        self._op = op
        self._tids = tids or []

    def run(self) -> None:
        from ..services import trash_service

        try:
            if self._op == "restore":
                n = 0
                for tid in self._tids:
                    trash_service.restore(self._backend, self._store, tid)
                    n += 1
                self.result.emit("restore", n, None)
            elif self._op == "delete":
                freed = 0
                n = 0
                for tid in self._tids:
                    row = self._store.get_trash(tid)
                    if not row:
                        continue
                    try:
                        self._backend.delete(row[2])
                    except Exception:  # noqa: BLE001
                        pass
                    freed += row[3]
                    self._store.delete_trash(tid)
                    n += 1
                self.result.emit("delete", n, freed)
            elif self._op == "empty":
                freed = trash_service.empty(self._backend, self._store)
                self.result.emit("empty", 0, freed)
            elif self._op == "expire":
                freed, n = trash_service.expire(self._backend, self._store)
                self.result.emit("expire", n, freed)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


