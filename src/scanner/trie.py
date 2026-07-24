"""路径前缀树:从扫描流增量构建,各节点累加子树文件字节。

设计要点:
- 根节点代表扫描根(如 ``/storage/emulated/0``),其直接子节点即顶层目录
  (Android / DCIM / Download …),供占用饼图直接取用。
- 仅**文件**的 own_size 计入各级 total;目录的 dir_size(块大小)不累加,
  避免目录元数据膨胀总量。
- 子节点 dict 懒创建(叶子文件占绝大多数,省内存),Node 用 __slots__。
"""
from __future__ import annotations


class Node:
    __slots__ = (
        "name", "children", "is_file", "own_size", "total",
        "mtime", "dir_size", "risk", "parent",
        "_sorted", "_sorted_gen",
    )

    def __init__(self, name: str):
        self.name = name
        self.children: dict[str, "Node"] | None = None
        self.is_file = False
        self.own_size = 0          # 文件:自身字节;目录:0
        self.total = 0             # 子树所有文件字节之和(含自身若为文件)
        self.mtime = 0             # 最新 mtime(unix 秒)
        self.dir_size = 0          # 目录:块大小(仅展示,不计入 total)
        self.risk: str | None = None   # M4 分类标签
        self.parent: "Node | None" = None
        self._sorted: list["Node"] | None = None     # 模型用排序缓存
        self._sorted_gen: int = -1

    def abs_path(self) -> str:
        """重建绝对路径(根节点 name 即扫描前缀)。"""
        parts: list[str] = []
        n: "Node | None" = self
        while n is not None and n.parent is not None:
            parts.append(n.name)
            n = n.parent
        # n 为根,name 为前缀(如 /storage/emulated/0)
        prefix = n.name if n is not None else ""
        if not parts:
            return prefix
        return prefix.rstrip("/") + "/" + "/".join(reversed(parts))


class FileTrie:
    def __init__(self, root_prefix: str):
        self.prefix = root_prefix.rstrip("/")
        self.root = Node(self.prefix or "/")
        self.file_count = 0
        self.dir_count = 0

    # --- 增量插入 ---
    def insert(self, abs_path: str, size: int, is_file: bool, mtime: int) -> Node:
        parts = self._rel_parts(abs_path)
        node = self.root
        chain: list[Node] = [node]
        for part in parts:
            ch = node.children
            if ch is None:
                ch = {}
                node.children = ch
            child = ch.get(part)
            if child is None:
                child = Node(part)
                child.parent = node
                ch[part] = child
            node = child
            chain.append(node)

        node.is_file = is_file
        if mtime > node.mtime:
            node.mtime = mtime
        if is_file:
            node.own_size = size
            self.file_count += 1
            for a in chain:            # 含叶子和根,逐级累加
                a.total += size
        else:
            node.dir_size = size
            self.dir_count += 1
        return node

    def _rel_parts(self, abs_path: str) -> list[str]:
        p = abs_path
        if p.startswith(self.prefix):
            p = p[len(self.prefix):]
        return [s for s in p.split("/") if s]

    # --- 查询 ---
    def top_level(self) -> list[tuple[str, int]]:
        """根的直接子节点 (名称, total),按 total 降序。"""
        ch = self.root.children or {}
        return sorted(((n.name, n.total) for n in ch.values()), key=lambda x: -x[1])

    @property
    def total_bytes(self) -> int:
        return self.root.total
