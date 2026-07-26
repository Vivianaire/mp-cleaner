"""SQLite 持久化层(标准库 sqlite3,无新依赖)。

per-device 库存于 ``mp-cleaner/data/<serial>/app.db``。v2.1 用 ``files``(快照)与
``scan_runs``(历史)两张表;``trash``/``phone_trash`` 在 v2.3 加入。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..adb.paths import ROOT as PROJECT_ROOT

_DATA_DIR = PROJECT_ROOT / "data"


def db_path_for(serial: str) -> Path:
    d = _DATA_DIR / serial
    d.mkdir(parents=True, exist_ok=True)
    return d / "app.db"


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        # check_same_thread=False:CleanToTrashWorker 等 QThread 会跨线程写(本应用
        # 各 Worker 串行执行,不会并发写同一连接,故安全)。
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self._schema()

    def _schema(self) -> None:
        c = self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime INTEGER NOT NULL,
                is_dir INTEGER NOT NULL,
                scanned_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS files_dir ON files(is_dir);

            CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                root TEXT NOT NULL,
                started INTEGER,
                finished INTEGER,
                file_count INTEGER,
                bytes INTEGER,
                source TEXT
            );

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS trash (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original TEXT NOT NULL,
                trash_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                category TEXT,
                moved_at INTEGER NOT NULL
            );
            """
        )
        self.conn.commit()

    # --- files 快照 ---
    def count_files(self, root: str) -> int:
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM files WHERE path LIKE ?", (root + "/%",)
        )
        return cur.fetchone()[0]

    def begin_replace(self, root: str, scanned_at: int) -> None:
        """开启一次全量替换:删除该 root 下旧记录。

        ``scanned_at`` 由调用方作为新快照时间戳复用(见 upsert_many),此处仅清旧行。
        """
        self.conn.execute("DELETE FROM files WHERE path LIKE ?", (root + "/%",))

    def upsert_many(self, rows) -> None:
        """rows: iterable of (path,size,mtime,is_dir,scanned_at)。"""
        self.conn.executemany(
            "INSERT OR REPLACE INTO files(path,size,mtime,is_dir,scanned_at) VALUES (?,?,?,?,?)",
            rows,
        )

    def commit(self) -> None:
        self.conn.commit()

    def iter_files(self, root: str):
        """yield (path,size,mtime,is_dir_bool)。"""
        cur = self.conn.execute(
            "SELECT path,size,mtime,is_dir FROM files WHERE path LIKE ?",
            (root + "/%",),
        )
        for path, size, mtime, is_dir in cur:
            yield (path, size, mtime, bool(is_dir))

    def get_dirs(self, root: str) -> dict[str, int]:
        cur = self.conn.execute(
            "SELECT path,mtime FROM files WHERE is_dir=1 AND path LIKE ?",
            (root + "/%",),
        )
        return {path: mtime for path, mtime in cur}

    # --- 历史 ---
    def add_scan_run(
        self, root, started, finished, file_count, nbytes, source
    ) -> None:
        self.conn.execute(
            "INSERT INTO scan_runs(root,started,finished,file_count,bytes,source)"
            " VALUES (?,?,?,?,?,?)",
            (root, started, finished, file_count, nbytes, source),
        )
        self.conn.commit()

    def list_scan_runs(self, root: str | None = None, limit: int = 200):
        """历史扫描记录(时间升序,便于画趋势)。

        返回 [(started, finished, file_count, bytes, source), ...]。给定 ``root``
        则只取该根;``limit`` 取最近 N 条后再正序返回。
        """
        if root is None:
            cur = self.conn.execute(
                "SELECT started,finished,file_count,bytes,source FROM ("
                "  SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?"
                ") ORDER BY started ASC",
                (limit,),
            )
        else:
            cur = self.conn.execute(
                "SELECT started,finished,file_count,bytes,source FROM ("
                "  SELECT * FROM scan_runs WHERE root=? ORDER BY id DESC LIMIT ?"
                ") ORDER BY started ASC",
                (root, limit),
            )
        return cur.fetchall()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    # --- 元数据(已装包等,缓存命中时复用)---
    def get_meta(self, key: str):
        cur = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)", (key, value)
        )
        self.conn.commit()

    # --- 回收站清单(自带安全删除)---
    def add_trash(self, original, size, category, moved_at) -> int:
        cur = self.conn.execute(
            "INSERT INTO trash(original,trash_path,size,category,moved_at)"
            " VALUES (?,?,?,?,?)",
            (original, "", size, category, moved_at),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_trash_path(self, tid: int, trash_path: str) -> None:
        self.conn.execute(
            "UPDATE trash SET trash_path=? WHERE id=?", (trash_path, tid)
        )
        self.conn.commit()

    def list_trash(self):
        cur = self.conn.execute(
            "SELECT id,original,trash_path,size,category,moved_at FROM trash"
            " ORDER BY moved_at DESC"
        )
        return cur.fetchall()

    def trash_total(self) -> int:
        cur = self.conn.execute("SELECT COALESCE(SUM(size),0) FROM trash")
        return cur.fetchone()[0]

    def get_trash(self, tid: int):
        cur = self.conn.execute(
            "SELECT id,original,trash_path,size,category,moved_at FROM trash WHERE id=?",
            (tid,),
        )
        return cur.fetchone()

    def trash_ids_older_than(self, cutoff: int):
        cur = self.conn.execute("SELECT id FROM trash WHERE moved_at < ?", (cutoff,))
        return [r[0] for r in cur.fetchall()]

    def delete_trash(self, tid: int) -> None:
        self.conn.execute("DELETE FROM trash WHERE id=?", (tid,))
        self.conn.commit()

    def clear_trash(self) -> None:
        self.conn.execute("DELETE FROM trash")
        self.conn.commit()
