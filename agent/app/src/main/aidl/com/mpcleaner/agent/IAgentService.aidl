package com.mpcleaner.agent;

/**
 * PC 经 Shizuku newProcessService 拿到此 binder,仅用于健康检查/触发 UserService 启动。
 * 实际数据(PC ↔ agent)走 TCP server(localhost:27042,经 adb forward),JSON 协议。
 */
interface IAgentService {
    boolean isAlive();
    int getPid();
}
