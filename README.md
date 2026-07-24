# mp-cleaner · 可视化手机清理

PC 端可视化全盘扫描 + 清理 Android 手机的桌面工具。**纯 ADB、免 Root**(shell uid 2000),
在 **OnePlus PGEM10 / Android 16** 真机验证通过。

## 功能

- **连机即用**:自动检测设备、识别未授权并提示,顶部显示存储容量(df);**首次连接自动扫描**,未连接时温和轮询,插上即识别
- **全深扫描**:无 maxdepth 限制,覆盖共享存储 + `Android/data`/`Android/obb` 应用外部缓存;SQLite 快照持久化 + **缓存重扫**(目录签名一致则秒级从快照重建);**连接停滞看门狗**(60s 无新数据自动中止并保留已扫部分,不再卡死)
- **仪表盘**:存储用量条 + **squarified treemap**(按目录类别着色,点击定位)+ 文件类型圆环 + 最大文件 + 存储洞察
- **深度分析**:per-app 占用(`dumpsys diskstats`,含 `/data/data` 私有数据,全盘 find 看不到的)+ 闲置态(`am get-inactive`,系统判长期未用)+ 重复文件采样哈希复核
- **趋势**:历次扫描占用走势
- **垃圾分类**:缓存 / 缩略图 / 已卸载残留 / 日志(安全,默认勾选)、大文件 / 重复文件(中等,仅列出)
- **回收站(双形态)**:
  - 自带回收站:清理默认 = **移入回收站(可恢复)**,支持恢复 / 永久删 / 清空 / 自动过期(>14 天)
  - 手机自带回收站:检测相册「最近删除」(MediaProvider `is_trashed`)与 `.trash` 目录,一键清空
- **自动分析**:建议引擎(按可回收排序)+ **一键优化**(自动执行安全建议)+ 建议卡片
- **安全护栏**:路径白名单、目录穿越防护、前台/运行中应用保护(其私有数据自动跳过)、回收站可恢复

## 运行

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
.venv/Scripts/pythonw.exe run.pyw                              # 无控制台,全程不弹终端窗
```

手机:开启「开发者选项 → USB 调试」,USB 连接后在手机弹窗点「允许」。
首次运行确保 `platform-tools/` 下有 `adb.exe`(见下)。

界面 6 个标签:**📊 仪表盘 · 🌲 空间浏览 · 🧹 垃圾清理 · 🗑 回收站 · 💡 建议 · 📈 趋势**。
工具栏:**▶ 扫描(F5)** / **⟳ 强制全扫(Ctrl+F5,忽略缓存)** / **⏹ 取消(Esc)** / **🧹 清理选中(Del)** / **📤 导出报告**。

> Windows 下所有 adb 子进程已加 `CREATE_NO_WINDOW`,用 `pythonw.exe` 运行不会弹出任何 cmd 黑窗。

## 平台工具(adb)

`platform-tools/` 内含 `adb.exe`(运行所需)。丢失则重新下载解压:
`https://dl.google.com/android/repository/platform-tools-latest-windows.zip`

## 架构(分层)

```
UI (PyQt6, 6 Tab)  →  Services(Scan/Cleanup/Trash/Device)  →  Domain+SQLite  →  DeviceBackend
  仪表盘/空间浏览/垃圾/回收站/建议/趋势                        FileTrie/快照/清单    └ AdbShellBackend(uid 2000)
```

```
src/
├── adb/           AdbClient(devices/shell/df/packages/diskstats/idle)+ paths(扫描命令/TRASH_DIR)
├── core/          backends(DeviceBackend 抽象 + AdbShellBackend)/ storage(SQLite)/
│                  appusage(深度分析)/ filetypes(扩展名→类型)/ recommend(建议引擎)
├── scanner/       FileTrie(路径前缀树,可持久化)+ TreeModel
├── classifier/    rules(垃圾分类)
├── cleaner/       lockdetect(前台/运行中应用保护)
├── services/      scan_service(全深+快照+缓存重扫)/ trash_service(回收站双形态)/ device_service
├── ui/            main_window + workers(QThread)+ widgets(treemap/donut/chart_panel/...)+
│                  views(dashboard/trash_view/recommendations/trends)
└── utils.py       human_size
run.pyw            入口(强制 utf-8 输出,防 GBK 控制台 emoji 崩溃)
data/<serial>/     per-device SQLite(app.db:files/scan_runs/trash/meta)
```

数据流:`ScannerWorker`(QThread)经 backend 流式拉取(**独立读取线程 + 有界队列 + 停滞看门狗 + 可取消**)
→ 主线程增量建 trie → 节流刷新 UI;扫完写 SQLite 快照 + 分类填垃圾面板 + 生成建议 + 后台深度分析。
清理经 `CleanToTrashWorker` 移入回收站。

## 设备适配要点(实测)

1. 扫描真实挂载点 `/storage/emulated/0`,不是 `/sdcard`(后者是 symlink,toybox find 不跟随)。
2. 类型符用 `%M`,非 `%Y`/`%y`(本机 toybox 不支持);`%M` 首字符 d/-/l。
3. 「已卸载残留」用**全量** `pm list packages`(含系统应用)判,非 `-3`(用 -3 会误判所有系统应用)。
4. adb shell 已是 shell uid(2000),可直接读写 `Android/data/<pkg>/cache`(应用外部缓存)——**免 Root、无需 Shizuku**。

## 已知限制

- 重复文件为「按大小预筛 + 采样哈希复核」候选(首尾各 128KB md5),非全量 MD5(过 adb 读全盘太慢)。
- 缓存重扫按目录 mtime 签名;文件原地改写(无增删)不会被缓存发现,下次全扫自愈。
- 大文件陈旧度用 mtime(Android 多 noatime)。
