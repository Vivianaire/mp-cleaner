"""扫描编排:全深扫描 + SQLite 快照持久化 + 缓存命中重扫。

缓存策略(秒级重扫的常见情形):
- 设备目录签名(各目录 mtime)与上次快照完全一致 → 直接从 SQLite 重建 trie,跳过 adb find。
- 否则 → 全深 find 扫描,完成后整表替换写回快照。

局限:目录 mtime 不变但文件被原地改写(无增删)的情形不会被缓存发现;下次全扫自愈。
"""
from __future__ import annotations

import json
import time

from ..core.backends import DeviceBackend
from ..core.storage import Store
from ..scanner.trie import FileTrie


class ScanService:
    def __init__(self, backend: DeviceBackend, store: Store):
        self.backend = backend
        self.store = store

    def has_snapshot(self, root: str) -> bool:
        return self.store.count_files(root) > 0

    def cached_packages(self) -> list[str]:
        raw = self.store.get_meta("packages")
        try:
            return json.loads(raw) if raw else []
        except (ValueError, TypeError):
            return []

    def try_cached(self, root: str) -> FileTrie | None:
        """目录签名一致则返回由快照重建的 trie,否则 None。"""
        if not self.has_snapshot(root):
            return None
        try:
            current = self.backend.list_dirs(root)
        except Exception:  # noqa: BLE001
            return None
        if current and current == self.store.get_dirs(root):
            return FileTrie.from_records(
                root,
                ((p, s, not d, m) for (p, s, m, d) in self.store.iter_files(root)),
            )
        return None

    def persist(
        self,
        root: str,
        trie: FileTrie,
        file_count: int,
        nbytes: int,
        packages: list[str] | None = None,
        source: str = "full",
    ) -> None:
        """整表替换写回快照 + 记录历史 + 存已装包。"""
        now = int(time.time())
        self.store.begin_replace(root, now)
        rows = (
            (p, sz, mt, 0 if isf else 1, now)
            for (p, sz, mt, isf) in trie.iter_nodes()
        )
        self.store.upsert_many(rows)
        self.store.commit()
        if packages:                       # 仅在拿到非空包列表时更新缓存
            self.store.set_meta("packages", json.dumps(packages))
        self.store.add_scan_run(root, now, now, file_count, nbytes, source)
