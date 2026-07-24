# mp-cleaner · 可视化手机清理

PC 端可视化全盘扫描 + 清理 Android 手机的桌面工具。基于 [cleanupMP.md](../cleanupMP.md)
调研报告中的**方案一(纯 ADB、免 Root)**,并已升级为完整产品(v2)。在 **OnePlus PGEM10
/ Android 16**(当前最高限制等级)真机验证通过。

## 功能

- **连机即用**:自动检测设备、识别未授权并提示,顶部显示存储容量(df)
- **全深扫描**:无 maxdepth 限制,覆盖共享存储 + `Android/data`/`Android/obb` 应用外部缓存;SQLite 快照持久化 + **缓存重扫**(目录签名一致则秒级从快照重建)
- **仪表盘**:存储用量条 + **squarified treemap**(按目录类别着色,点击定位)+ 文件类型圆环 + 最大文件 + 存储洞察
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
.venv/Scripts/python.exe run.pyw
```

手机:开启「开发者选项 → USB 调试」,USB 连接后在手机弹窗点「允许」。
首次运行确保 `platform-tools/` 下有 `adb.exe`(见下)。

界面为 5 个标签:**📊 仪表盘 · 🌲 空间浏览 · 🧹 垃圾清理 · 🗑 回收站 · 💡 建议**。
工具栏:**▶ 扫描(F5)** / **⟳ 强制全扫(Ctrl+F5,忽略缓存)** / **🧹 清理选中(Del)**。

## 平台工具(adb)

`platform-tools/` 内含 `adb.exe`(运行所需)。丢失则重新下载解压:
`https://dl.google.com/android/repository/platform-tools-latest-windows.zip`

## 架构(分层)

```
UI (PyQt6, 5 Tab)  →  Services(Scan/Cleanup/Trash/Device)  →  Domain+SQLite  →  DeviceBackend
  仪表盘/空间浏览/垃圾/回收站/建议                                 FileTrie/快照/清单     ├ AdbShellBackend(uid 2000)
                                                                                      └ ShizukuAgentBackend(v3)
```

```
src/
├── adb/           AdbClient(devices/shell/df/packages)+ paths(扫描命令/TRASH_DIR)
├── core/          backends(DeviceBackend 抽象 + AdbShellBackend)/ storage(SQLite)/
│                  filetypes(扩展名→类型)/ recommend(建议引擎)
├── scanner/       FileTrie(路径前缀树,可持久化)+ TreeModel
├── classifier/    rules(六类垃圾分类)
├── cleaner/       lockdetect(前台/运行中应用保护)
├── services/      scan_service(全深+快照+缓存重扫)/ trash_service(回收站双形态)/
│                  device_service(df/包名/前台)
├── ui/            main_window(5 Tab) + workers(QThread)+ widgets(treemap/donut/...)+
│                  views(dashboard/trash_view/recommendations)
└── utils.py       human_size
run.pyw            入口(强制 utf-8 输出,防 GBK 控制台 emoji 崩溃)
data/<serial>/     per-device SQLite(app.db:files/scan_runs/trash/meta)
```

数据流:`ScannerWorker`(QThread)经 backend 流式拉取 → 主线程增量建 trie → 节流刷新 UI;
扫完写 SQLite 快照 + 分类填垃圾面板 + 生成建议。清理经 `CleanToTrashWorker` 移入回收站。

## 设备适配要点(实测,偏离报告原文)

1. 扫描真实挂载点 `/storage/emulated/0`,不是 `/sdcard`(后者是 symlink,toybox find 不跟随)。
2. 类型符用 `%M`,非报告的 `%Y`/`%y`(本机 toybox 不支持);`%M` 首字符 d/-/l。
3. 「已卸载残留」用**全量** `pm list packages`(含系统应用)判,非 `-3`(用 -3 会误判所有系统应用)。
4. adb shell 已是 shell uid(2000,与 Shizuku 同级),可直接读写 `Android/data/<pkg>/cache`(应用外部缓存)——**Shizuku 对 PC 工具并非必需**。

## v3 路线(Shizuku Agent,未做)

Shizuku 对 PC 驱动工具的真正增量价值在 **on-device Agent app**(原生扫描提速、ContentProvider
媒体回收站原生清空、更稳的 Android/data 写入),需:Android SDK + Gradle 构建 APK + 手机装 Shizuku。
本机目前无 Android SDK;v3 作为独立子项目,确认后再开工。`DeviceBackend` 抽象已为其预留。

## 已知限制

- 重复文件为「按大小预筛」候选,未做 MD5 全量校验(过 adb 读全盘太慢)。
- 缓存重扫按目录 mtime 签名;文件原地改写(无增删)不会被缓存发现,下次全扫自愈。
- 大文件陈旧度用 mtime(Android 多 noatime)。
