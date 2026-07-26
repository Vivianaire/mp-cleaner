package com.mpcleaner.agent

import android.os.Process
import android.util.Log

/**
 * Shizuku UserService:Shizuku(adb 启动时为 uid 2000)在子进程实例化本类。
 * 构造时启动 TCP server;PC 经 `adb forward tcp:27042 tcp:27042` 连入,JSON 协议。
 * 数据(扫描/文件/媒体回收站)全部在本进程执行,不经 USB 长连接。
 *
 * 注:Shizuku UserService 必须 implement IBinder,这里继承 IAgentService.Stub(AIDL)。
 */
class AgentService : IAgentService.Stub() {
    init {
        Log.i(TAG, "constructed uid=${Process.myUid()} pid=${Process.myPid()}")
        Server.start()
    }

    override fun isAlive(): Boolean = Server.isRunning()
    override fun getPid(): Int = Process.myPid()

    private companion object {
        private const val TAG = "AgentService"
    }
}
