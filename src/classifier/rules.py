"""垃圾文件分类规则(据报告「垃圾文件智能分类与风险评估模型」表)。

类别与风险:
- 缓存 / 缩略图 / 已卸载残留 / 日志  -> 安全(默认勾选)
- 大文件 / 重复文件                 -> 中等(仅列出,不自动勾选)

规则要点:
- 目录类目(缓存/缩略图/残留)整体覆盖其子树:命中后不再细分子项,避免重复。
- 一个节点只进一个类别(yielded 集合)。
- 大文件用 mtime 判定陈旧(Android 多 noatime,atime 不可靠)。
- 重复文件先「按大小预筛」出候选(过 adb 读全盘做全量 MD5 太慢);候选再由后台
  ``DedupWorker`` 采样哈希(首尾各 128KB 的 md5)复核,剔除同大小但内容不同者。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..scanner.trie import FileTrie, Node

LARGE_FILE_BYTES = 100 * 1024 * 1024          # 100 MB
STALE_SECS = 180 * 24 * 3600                  # 半年
DUP_MIN_BYTES = 5 * 1024 * 1024               # 重复候选最小体积

CATEGORY_ORDER = ["缓存", "缩略图", "已卸载残留", "日志", "大文件", "重复文件"]
RISK = {
    "缓存": "安全",
    "缩略图": "安全",
    "已卸载残留": "安全",
    "日志": "安全",
    "大文件": "中等",
    "重复文件": "中等",
}
DEFAULT_CHECK = {
    "缓存": True,
    "缩略图": True,
    "已卸载残留": True,
    "日志": True,
    "大文件": False,
    "重复文件": False,
}

# 目录名(小写)匹配
_CACHE_NAMES = {"cache", "__cache__", "caches", ".cache", "temp", "tmp", "tempcache"}
_THUMB_NAMES = {".thumbnails", ".thumbdata", ".thumbs", "thumbnails"}


@dataclass
class JunkItem:
    category: str
    risk: str
    node: Node
    size: int
    path: str
    protected: bool = False


def _is_residue(node: Node, installed: set[str]) -> bool:
    """Android/data|obb/<pkg> 且 <pkg> 未安装。"""
    p = node.parent
    if p is None or p.name not in ("data", "obb"):
        return False
    pp = p.parent
    if pp is None or pp.name != "Android":
        return False
    return node.name not in installed


def _categorize(node: Node, installed: set[str]) -> str | None:
    """返回该节点命中的类别(目录类目或日志),否则 None。"""
    if not node.is_file:
        lname = node.name.lower()
        # installed 为空 = pm 查询失败,而非真的没装应用(真机必有数百个)。
        # 此时**跳过残留判定**,否则会把所有 Android/data/* 误标为「已卸载残留」
        # (安全类,默认勾选、可一键删),酿成误删活数据。
        if installed and _is_residue(node, installed):
            return "已卸载残留"
        if lname in _THUMB_NAMES:
            return "缩略图"
        if lname in _CACHE_NAMES:
            return "缓存"
        return None
    # 文件:仅日志在此判定(大文件/重复走另一支,避免与目录逻辑混淆)
    lname = node.name.lower()
    if lname.endswith(".log") or lname.endswith(".err") or "error_log" in lname:
        return "日志"
    return None


def classify(trie: FileTrie, installed_pkgs, now_ts: float) -> list[JunkItem]:
    """遍历 trie,产出按类别归组的垃圾项。"""
    installed = set(installed_pkgs)
    items: list[JunkItem] = []
    dup_by_size: dict[int, list[Node]] = {}
    yielded: set[int] = set()

    def emit(cat: str, node: Node, size: int) -> None:
        if id(node) in yielded:
            return
        yielded.add(id(node))
        items.append(
            JunkItem(
                category=cat,
                risk=RISK[cat],
                node=node,
                size=size,
                path=node.abs_path(),
            )
        )

    def walk(node: Node) -> None:
        cat = _categorize(node, installed)
        if cat is not None:
            emit(cat, node, node.total if not node.is_file else node.own_size)
            return  # 目录:子树整体覆盖,不再细分;文件:无子树
        if node.is_file:
            sz = node.own_size
            if sz >= LARGE_FILE_BYTES and (now_ts - node.mtime) >= STALE_SECS:
                emit("大文件", node, sz)
            if sz >= DUP_MIN_BYTES:
                dup_by_size.setdefault(sz, []).append(node)
            return
        for child in (node.children or {}).values():
            walk(child)

    for child in (trie.root.children or {}).values():
        walk(child)

    # 重复文件(按大小预筛)
    for nodes in dup_by_size.values():
        if len(nodes) > 1:
            for n in nodes:
                emit("重复文件", n, n.own_size)

    return items
