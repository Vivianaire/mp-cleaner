"""回收站服务:工具自带安全删除(可恢复)+ 手机自带回收站检测/清空。

自带回收站:清理 = ``mv`` 到 ``/storage/emulated/0/.mp_cleaner/.trash/<id><rel>``,
清单写 SQLite ``trash`` 表(可恢复/过期/清空)。相对路径保留以便恢复到原位。

手机自带回收站:① 目录式(.trash/.Trashes)② MediaProvider 的 ``is_trashed=1``
(相册最近删除主力)。检测只读,清空按来源 dispatch。
"""
from __future__ import annotations

import re
import time

from ..adb.paths import SCAN_ROOT, TRASH_DIR
from ..core.backends import DeviceBackend
from ..core.storage import Store

_EXPIRE_DAYS = 14
_MEDIA_URIS = [
    ("图片", "content://media/external/images/media"),
    ("视频", "content://media/external/video/media"),
    ("音频", "content://media/external/audio/media"),
]
_SIZE_RE = re.compile(r"_size=(\d+)")


# ===== 自带回收站 =====
def move_to_trash(backend: DeviceBackend, store: Store, item) -> int:
    """把一项移入回收站,返回 trash id。调用方需已做保护/安全过滤。"""
    moved_at = int(time.time())
    rel = item.path[len(SCAN_ROOT):]                  # 形如 /Android/data/x/cache
    tid = store.add_trash(item.path, item.size, item.category, moved_at)
    trash_path = f"{TRASH_DIR}/{tid}{rel}"
    parent = trash_path.rsplit("/", 1)[0]
    if parent:
        backend.mkdir(parent)
    backend.move(item.path, trash_path)
    store.set_trash_path(tid, trash_path)
    return tid


def restore(backend: DeviceBackend, store: Store, tid: int) -> str | None:
    """把 trash 项移回原路径(若已存在则加 .restored),返回目标路径。"""
    row = store.get_trash(tid)
    if not row:
        return None
    _id, original, trash_path, _size, _cat, _moved = row
    dest = original
    if _exists(backend, original):
        dest = f"{original}.restored"
    parent = dest.rsplit("/", 1)[0]
    if parent:
        backend.mkdir(parent)
    backend.move(trash_path, dest)
    store.delete_trash(tid)
    return dest


def empty(backend: DeviceBackend, store: Store) -> int:
    """永久清空整个回收站,返回释放字节数。"""
    freed = store.trash_total()
    backend.delete(TRASH_DIR)
    backend.mkdir(TRASH_DIR)
    store.clear_trash()
    return freed


def expire(backend: DeviceBackend, store: Store, days: int = _EXPIRE_DAYS):
    """清理超过 N 天的回收项,返回 (释放字节, 清理条数)。"""
    cutoff = int(time.time()) - days * 86400
    freed = 0
    n = 0
    for tid in store.trash_ids_older_than(cutoff):
        row = store.get_trash(tid)
        if not row:
            continue
        try:
            backend.delete(row[2])
        except Exception:  # noqa: BLE001
            pass
        freed += row[3]
        store.delete_trash(tid)
        n += 1
    return freed, n


def _exists(backend: DeviceBackend, path: str) -> bool:
    out = backend.shell(f"test -e {_q(path)} && echo Y || echo N", timeout=10)
    return "Y" in out


# ===== 手机自带回收站 =====
def detect_phone_trash(backend: DeviceBackend) -> list[dict]:
    """返回 [{label, kind('dir'|'media'), key, size}],只读。"""
    items: list[dict] = []
    # 目录式 trash
    out = backend.shell(
        rf"find {SCAN_ROOT} -maxdepth 4 -type d \( -name '.trash' -o -name '.Trashes' \) "
        rf"-printf '%p\n'",
        timeout=60,
    )
    for line in out.splitlines():
        d = line.strip()
        if not d or "/.mp_cleaner/" in d:
            continue
        size = _du(backend, d)
        if size > 0:
            items.append({"label": d, "kind": "dir", "key": d, "size": size})
    # MediaProvider is_trashed(相册最近删除)
    for label, uri in _MEDIA_URIS:
        count, total = _media_trash(backend, uri)
        if total > 0:
            items.append(
                {"label": f"相册回收站 · {label}({count} 项)", "kind": "media",
                 "key": uri, "size": total}
            )
    return items


def empty_phone_trash(backend: DeviceBackend, target: dict) -> int:
    """按来源清空一项手机回收站,返回其大小(估算)。"""
    freed = target.get("size", 0)
    if target["kind"] == "dir":
        backend.delete(target["key"])
    else:  # media
        backend.shell(
            f"content delete --uri {target['key']} --where \"is_trashed=1\"", timeout=60
        )
    return freed


def _du(backend: DeviceBackend, path: str) -> int:
    out = backend.shell(f"du -sk {_q(path)} 2>/dev/null", timeout=30)
    try:
        return int(out.strip().split()[0]) * 1024
    except (ValueError, IndexError):
        return 0


def _media_trash(backend: DeviceBackend, uri: str):
    out = backend.shell(
        f'content query --uri {uri} --projection _size --where "is_trashed=1"',
        timeout=30,
    )
    total = sum(int(m) for m in _SIZE_RE.findall(out))
    count = out.count("Row:")
    return count, total


def _q(p: str) -> str:
    return "'" + p.replace("'", "'\\''") + "'"
