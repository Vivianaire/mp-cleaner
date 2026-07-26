package com.mpcleaner.agent

/** 构造 find 命令,输出格式与 PC 端 src/adb/paths.py 完全一致:path|size|mode|mtime。 */
object ScanCmd {
    private const val SCAN_ROOT = "/storage/emulated/0"
    private const val EXCLUDE = "/storage/emulated/0/.mp_cleaner"   // 工具自身回收站,扫描时剪除
    private const val FMT = "%p|%s|%M|%T@"

    /** maxdepth<=0 表示无深度限制(全深)。 */
    fun scan(root: String = SCAN_ROOT, maxdepth: Int = 0): String {
        val md = if (maxdepth > 0) "-maxdepth $maxdepth " else ""
        val prune = if (root == SCAN_ROOT) "-path '$EXCLUDE' -prune -o " else ""
        return "find $root -mindepth 1 $md${prune}-printf '$FMT\\n'"
    }

    fun listDirs(root: String = SCAN_ROOT): String =
        "find $root -type d -printf '%p|%T@\\n'"
}
