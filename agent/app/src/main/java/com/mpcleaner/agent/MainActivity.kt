package com.mpcleaner.agent

import android.content.ComponentName
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.IBinder
import android.util.Log
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import rikka.shizuku.Shizuku

class MainActivity : AppCompatActivity() {

    private lateinit var statusText: TextView
    private lateinit var actionBtn: Button
    private var agent: IAgentService? = null
    private var permissionGranted = false

    private val onBinderReceived = Shizuku.OnBinderReceivedListener { runOnUiThread { onBinderState() } }
    private val onBinderDead = Shizuku.OnBinderDeadListener { runOnUiThread { onBinderState() } }
    private val onPermResult = Shizuku.OnRequestPermissionResultListener { _, grantResult ->
        permissionGranted = grantResult == PackageManager.PERMISSION_GRANTED
        runOnUiThread { onBinderState() }
    }

    private val conn = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
            Log.d(TAG, "onServiceConnected")
            agent = IAgentService.Stub.asInterface(service)
            runOnUiThread { updateUI() }
        }
        override fun onServiceDisconnected(name: ComponentName?) {
            Log.d(TAG, "onServiceDisconnected")
            agent = null
            runOnUiThread { updateUI() }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(56, 56, 56, 56)
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
            )
        }
        statusText = TextView(this).apply { textSize = 16f; setPadding(0, 0, 0, 64) }
        actionBtn = Button(this).apply {
            text = "检查 / 启动 Agent"
            setOnClickListener {
                Log.d(TAG, "button clicked")
                onAction()
            }
        }
        root.addView(statusText)
        root.addView(actionBtn)
        setContentView(root)

        Shizuku.addBinderReceivedListener(onBinderReceived)
        Shizuku.addBinderDeadListener(onBinderDead)
        Shizuku.addRequestPermissionResultListener(onPermResult)
        onBinderState()
    }

    override fun onDestroy() {
        super.onDestroy()
        Shizuku.removeBinderReceivedListener(onBinderReceived)
        Shizuku.removeBinderDeadListener(onBinderDead)
        Shizuku.removeRequestPermissionResultListener(onPermResult)
        try {
            if (agent != null) Shizuku.unbindUserService(userServiceArgs(), conn, true)
        } catch (_: Exception) {
        }
    }

    private fun userServiceArgs() = Shizuku.UserServiceArgs(
        ComponentName(packageName, AgentService::class.java.name)
    ).processNameSuffix("agent").tag("mpcleaner-agent")

    private fun onBinderState() {
        val binder = Shizuku.pingBinder()
        // checkSelfPermission 要求 binder 已收到,否则抛 IllegalStateException
        val granted = if (binder) {
            Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
        } else false
        permissionGranted = granted
        Log.d(TAG, "onBinderState binder=$binder granted=$granted agent=${agent != null}")
        if (binder && granted && agent == null) startAgent()
        updateUI()
    }

    private fun onAction() {
        val binder = Shizuku.pingBinder()
        val granted = if (binder) {
            Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
        } else false
        Log.d(TAG, "onAction binder=$binder granted=$granted agent=${agent != null}")
        when {
            !binder ->
                statusText.text = "Shizuku 未运行:打开 Shizuku app,用 adb 或 root 启动"
            !granted -> Shizuku.requestPermission(REQ_PERM)
            agent == null -> startAgent()
        }
        updateUI()
    }

    private fun startAgent() {
        Log.d(TAG, "startAgent: call bindUserService")
        try {
            Shizuku.bindUserService(userServiceArgs(), conn)
        } catch (e: Exception) {
            Log.e(TAG, "startAgent failed", e)
            statusText.text = "启动 Agent 失败:$e"
        }
    }

    private fun updateUI() {
        val alive = try { agent?.isAlive == true } catch (e: Exception) { false }
        val pid = try { agent?.pid ?: -1 } catch (e: Exception) { -1 }
        statusText.text = buildString {
            append("Shizuku:${if (Shizuku.pingBinder()) "运行中" else "未运行"}\n")
            append("授权:${if (permissionGranted) "已授权" else "未授权"}\n")
            append("Agent 服务:${if (alive) "在线(pid=$pid,端口 27042)" else "未启动"}\n\n")
            append("PC 侧:mp-cleaner 启用「Shizuku 加速」")
        }
    }

    private companion object {
        const val REQ_PERM = 1
        const val TAG = "MPC_AGENT"
    }
}
