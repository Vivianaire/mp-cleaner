package com.mpcleaner.agent

import android.os.Process
import android.util.Log
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

/**
 * 本地 TCP server(localhost:27042)。PC 经 adb forward 连入。
 * 协议:一行 JSON 请求 {"cmd":"...","args":{...}};
 * 响应:单行 JSON(普通命令)或 NDJSON 流(scan:多行 {"r":"..."} + 末行 {"end":true})。
 */
object Server {
    private const val PORT = 27042
    private const val TAG = "AgentServer"
    @Volatile private var running = false

    fun isRunning(): Boolean = running

    fun start() {
        if (running) return
        running = true
        thread(name = "agent-server", isDaemon = true) {
            try {
                val server = ServerSocket(PORT)
                Log.i(TAG, "listening on $PORT pid=${Process.myPid()}")
                while (running) {
                    val client = server.accept()
                    thread(name = "agent-conn", isDaemon = true) { handle(client) }
                }
            } catch (e: Exception) {
                Log.e(TAG, "server died", e)
                running = false
            }
        }
    }

    private fun handle(socket: Socket) {
        try {
            socket.use { s ->
                val reader = BufferedReader(InputStreamReader(s.getInputStream(), Charsets.UTF_8))
                val writer = OutputStreamWriter(s.getOutputStream(), Charsets.UTF_8)
                val line = reader.readLine() ?: return
                val req = JSONObject(line)
                dispatch(req.optString("cmd"), req.optJSONObject("args") ?: JSONObject(), writer)
                writer.flush()
            }
        } catch (e: Exception) {
            Log.e(TAG, "handle fail", e)
        }
    }

    private fun dispatch(cmd: String, args: JSONObject, out: OutputStreamWriter) {
        try {
            when (cmd) {
                "ping" -> json(out, "ok" to true, "pid" to Process.myPid())
                "scan" -> scan(args, out)
                "list_dirs" -> json(out, "result" to Shell.run(ScanCmd.listDirs(args.optString("root"))))
                "df" -> json(out, "result" to Shell.run("df -k " + args.optString("path", "/storage/emulated/0")))
                "installed_packages" -> json(out, "result" to Shell.run("pm list packages"))
                "third_party_packages" -> json(out, "result" to Shell.run("pm list packages -3"))
                "foreground_packages" -> json(out, "result" to
                    Shell.run("dumpsys activity activities") + "\n---recents---\n" + Shell.run("dumpsys activity recents"))
                "shell" -> json(out, "result" to Shell.run(args.optString("command", "")))
                "move" -> json(out, "result" to Shell.run("mv " + args.optString("src", "") + " " + args.optString("dst", "")))
                "delete" -> json(out, "result" to Shell.run("rm -rf " + args.optString("path", "")))
                "mkdir" -> json(out, "result" to Shell.run("mkdir -p " + args.optString("path", "")))
                "disk_stats" -> json(out, "result" to Shell.run("dumpsys diskstats"))
                "app_idle" -> json(out, "result" to Shell.run("am get-inactive " + args.optString("pkg", "")))
                "force_stop" -> json(out, "result" to Shell.run("am force-stop " + args.optString("pkg", "")))
                // MediaStore「最近删除」(is_trashed=1)经 content 命令清空
                "media_trash_clear" -> json(out, "result" to
                    Shell.run("content delete --uri content://media/external --where \"is_trashed=1\""))
                else -> json(out, "error" to "unknown cmd: $cmd")
            }
        } catch (e: Exception) {
            json(out, "error" to (e.toString()))
        }
    }

    /** 流式扫描:本地 find,每条 record 一行 NDJSON 转发,末行 end 标记。 */
    private fun scan(args: JSONObject, out: OutputStreamWriter) {
        val root = args.optString("root", "/storage/emulated/0")
        val maxdepth = args.optInt("maxdepth", 0)      // 0 = 无限制
        Shell.runStream(ScanCmd.scan(root, maxdepth)) { record ->
            out.write(JSONObject().put("r", record).toString())
            out.write("\n")
            out.flush()
        }
        out.write(JSONObject().put("end", true).toString())
        out.write("\n")
    }

    private fun json(out: OutputStreamWriter, vararg kv: Pair<String, Any>) {
        val o = JSONObject()
        for ((k, v) in kv) o.put(k, v)
        out.write(o.toString())
        out.write("\n")
    }
}
