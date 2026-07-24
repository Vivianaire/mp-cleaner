# mp-cleaner

Windows 桌面端的 Android 存储清理工具。经 ADB(免 Root,shell uid 2000)扫描共享存储
与应用外部缓存,识别垃圾文件并移入可恢复回收站。PyQt6 实现,真机验证。

## 功能

- 全深扫描 `/storage/emulated/0`,覆盖 `Android/data`、`Android/obb` 应用外部缓存
- SQLite 快照持久化;目录签名一致时从快照重建,跳过全盘扫描
- 垃圾分类:缓存、缩略图、已卸载残留、日志、废弃文件、空文件夹、大文件、重复文件
  (安全类默认勾选;系统应用的缓存与废弃项标为中等,默认不清理)
- 回收站:工具自带(移入即 mv,可恢复 / 过期 / 清空)+ 手机自带(相册最近删除、`.trash`)
- per-app 占用(`dumpsys diskstats` + `am get-inactive` 闲置态)、占用趋势、重复文件采样哈希复核
- 安全护栏:路径必须在扫描根下、目录穿越防护、前台 / 运行中应用的私有数据自动跳过

## 运行

Python 3.13+、Windows。`platform-tools/` 需含 `adb.exe`(见下)。

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/pythonw run.pyw
```

手机开启「开发者选项 → USB 调试」,USB 连接后在手机弹窗授权。Windows 下 adb 子进程
已加 `CREATE_NO_WINDOW`,用 `pythonw` 运行不会弹出控制台窗口。

## adb

`platform-tools/` 需含 `adb.exe`。丢失则从
<https://dl.google.com/android/repository/platform-tools-latest-windows.zip> 下载解压。

## 架构

```
UI (PyQt6)  →  Services  →  Domain + SQLite  →  DeviceBackend
                                    ├ AdbShellBackend (uid 2000, adb shell)
                                    └ (可扩展后端)
```

```
src/
  adb/         AdbClient、扫描命令、路径常量
  core/        backends、storage(SQLite)、appusage、recommend、filetypes
  scanner/     FileTrie(路径前缀树)、TreeModel
  classifier/  垃圾分类规则
  cleaner/     前台应用保护
  services/    scan / trash / device 服务编排
  ui/          main_window、workers(QThread)、widgets、views、theme
run.pyw        入口
data/<serial>/  per-device SQLite(app.db)
```

扫描在 QThread 中经独立读取线程 + 有界队列流式拉取,带停滞看门狗(60s 无新数据则中止
并保留已扫部分);主线程增量构建 trie。完成后写快照、分类、生成建议,深度分析在后台
线程。UI 配色集中于 `src/ui/theme.py`,提供浅 / 深双主题(工具栏切换)。

## 设备适配要点

- 扫描真实挂载点 `/storage/emulated/0`(`/sdcard` 是 symlink,toybox find 不跟随)
- 类型符用 `%M`(本机 toybox 不支持 `%Y` / `%y`),首字符 d / - / l 表示目录 / 文件 / 符号链接
- 已卸载残留按全量 `pm list packages` 判定(用 `-3` 会把系统应用误判为残留)
- adb shell 已是 uid 2000,可直接读写 `Android/data/<pkg>/cache`,无需 Root 或 Shizuku

## 已知限制

- 重复文件为「按大小预筛 + 首尾各 128KB 采样哈希复核」,非全量 MD5(全盘读耗时)
- 缓存重扫按目录 mtime 签名;文件原地改写(无增删)不会被识别,下次全扫自愈
- 大文件陈旧度用 mtime(Android 多为 noatime,atime 不可靠)
