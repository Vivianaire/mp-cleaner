package com.mpcleaner.agent

import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader

/** 在 Shizuku 进程(uid 2000)内执行 shell 命令,经 /system/bin/sh。 */
object Shell {
    private const val TAG = "Shell"

    fun run(cmd: String): String {
        if (cmd.isEmpty()) return ""
        return try {
            val proc = Runtime.getRuntime().exec(arrayOf("/system/bin/sh", "-c", cmd))
            val out = proc.inputStream.bufferedReader().use { it.readText() }
            proc.waitFor()
            out
        } catch (e: Exception) {
            Log.e(TAG, "run fail: $cmd", e)
            ""
        }
    }

    /** 流式:逐行回调(onLine),适合 find 这种大量输出的命令。 */
    fun runStream(cmd: String, onLine: (String) -> Unit) {
        try {
            val proc = Runtime.getRuntime().exec(arrayOf("/system/bin/sh", "-c", cmd))
            BufferedReader(InputStreamReader(proc.inputStream, Charsets.UTF_8)).use { r ->
                var line = r.readLine()
                while (line != null) {
                    onLine(line)
                    line = r.readLine()
                }
            }
            proc.waitFor()
        } catch (e: Exception) {
            Log.e(TAG, "runStream fail: $cmd", e)
        }
    }
}
