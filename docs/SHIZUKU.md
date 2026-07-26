# Shizuku 加速(可选扩展)

mp-cleaner 默认走 adb(免 Root)。启用 **Shizuku + agent** 后,扫描与文件操作在**手机本地执行**(不经 USB 长连接),海量小文件目录(微信/QQ 缓存)扫描更快、文件操作更稳。

> 不增加清理范围:`/data/data` 等私有数据仍需 root。Shizuku(adb 启动)= uid 2000,和 adb shell 同级。

## 1. 手机装并启动 Shizuku

1. 装 Shizuku APK:<https://shizuku.rikka.app/download/>
2. USB 连手机(开 USB 调试),电脑执行:
   ```
   adb shell sh /storage/emulated/0/Android/data/moe.shizuku.privileged.api/start.sh
   ```
3. Shizuku app 内显示「运行中」即成功(**每次重启手机需重做这步**,除非已 root)

## 2. 构建 agent APK

`agent/` 是独立 Android 工程,用 **Android Studio** 打开 `mp-cleaner/agent/` 目录:

- IDE 会自动下载 Gradle wrapper jar、依赖、所需 SDK 组件
- Gradle sync 完成后:Build → Build Bundle(s) / APK(s) → Build APK
- 产物:`agent/app/build/outputs/apk/debug/app-debug.apk`

命令行(若已设 `ANDROID_SDK_HOME`):
```
cd agent
./gradlew assembleDebug        # Windows: gradlew.bat assembleDebug
```

## 3. 装 agent 并授权

```
adb install path/to/app-debug.apk
```

手机打开「**mp-cleaner Agent**」app:
1. 点「检查 / 启动 Agent」→ 系统弹 Shizuku 授权 → 允许
2. 界面显示 `Agent 服务:在线(pid=…,端口 27042)`

## 4. 在 mp-cleaner 启用

PC 端 mp-cleaner 工具栏点「**⚡ Shizuku 加速**」(可勾选):
- 状态栏显示「已启用 Shizuku 加速」→ 扫描/清理经 agent
- 取消勾选 / agent 掉线 / Shizuku 停 → **自动回 adb**,功能不中断

## 故障排查

| 现象 | 处理 |
|---|---|
| 「未安装 agent APK」 | `adb install` agent APK |
| 「agent 服务未起」 | 手机打开 agent app,点「启动」;确认 Shizuku 在运行 |
| 「adb forward 失败」 | 检查 USB 连接、`adb devices` 能看到设备 |
| 扫描中途切回 adb | agent 进程被杀(Shizuku 停),重启 Shizuku + agent |
