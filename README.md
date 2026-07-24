# mp-cleaner · 可视化手机清理

PC 端可视化全盘扫描 + 清理 Android 手机的桌面工具。基于 [cleanupMP.md](../cleanupMP.md)
调研报告中的**方案一(纯 ADB、免 Root 基础版)**:手机端零安装、零提权,所有操作经
USB ADB 由 PC 端下发。

在 **OnePlus PGEM10 / Android 16**(当前最高限制等级)真机验证通过。

## 功能

- 连机即用:自动检测设备、识别未授权并提示
- 流式全盘扫描:`toybox find -printf` 单命令拉取全盘元数据,实时增量构建占用树
- 可视化:左侧目录占用树(名称/大小/占比/类型/风险),右侧顶层目录占用分布条形图
- 垃圾分类:缓存 / 缩略图 / 已卸载残留 / 日志(安全,默认勾选)、大文件 / 重复文件(中等,仅列出)
- 安全清理:勾选 → 确认 → 批量 `rm -rf`;**前台与最近活动应用的私有数据自动跳过**;路径白名单 + 目录穿越防护

## 运行

```bash
# 首次:建虚拟环境并装依赖
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows

# 启动(开发期,带控制台日志)
.venv/Scripts/python.exe run.pyw
# 或双击 run.pyw(用 pythonw,无控制台窗口)
```

手机:开启「开发者选项 → USB 调试」,USB 连接后在手机弹窗点「允许」。
首次运行确保 `platform-tools/` 下有 `adb.exe`(见下)。

## 平台工具(adb)

`platform-tools/` 内含 Android Platform Tools 的 `adb.exe`(运行所需)。若丢失,
重新下载解压:

```
https://dl.google.com/android/repository/platform-tools-latest-windows.zip
```

## 架构

```
src/
├── adb/           AdbClient:设备枚举 / one-shot shell / 流式 popen;paths.py 扫描命令
├── scanner/       FileTrie(路径前缀树,增量字节累加)+ TreeModel(QAbstractItemModel)
├── classifier/    rules.py:按报告分类表把节点归入风险/用途等级
├── cleaner/       lockdetect.py:前台/运行中应用保护检测
├── ui/            MainWindow + workers(QThread)+ widgets(设备面板/树/占用图/垃圾面板)
└── utils.py       字节人类可读化
run.pyw            入口
```

数据流:`ScannerWorker`(QThread)跑 `find`,节流发 `batchReady` → 主线程把记录塞进
`FileTrie` → 节流 `QTimer`(250ms)刷新 `TreeModel` + 占用图,UI 不卡顿。扫描结束后
`classify()` 产出垃圾项填入 `JunkPanel`。清理时 `CleanerWorker` 先做保护检测再逐项删除。

## 设备适配要点(实测,偏离报告原文)

1. **扫描路径用 `/storage/emulated/0`**,不是 `/sdcard`——后者是 symlink,toybox `find`
   默认不跟随起始点 symlink。
2. **类型符用 `%M`**,不是报告写的 `%Y`/`%y`——本机 toybox `find -printf` 不支持后者;
   `%M` 首字符 `d`/`-`/`l` 表目录/文件/符号链接。最终命令:
   `find /storage/emulated/0 -mindepth 1 -maxdepth 6 -printf '%p|%s|%M|%T@\n'`
3. **「已卸载残留」用全量 `pm list packages`(含系统应用)判定**,而非报告的 `-3`
   (仅第三方)——用 `-3` 会把所有系统应用(com.oplus.*/com.android.*…)误判为残留。
4. **删除走 `adb shell rm -rf`**(非 MTP)——在 Android 16 上对 `/sdcard` 可写可用。

## 安全机制

- 路径白名单:删除目标必须在 `/storage/emulated/0/` 之下,不得为根自身、不得含 `..`
- 动态保护:删除前取前台 + 最近活动应用包名(与已装包取交集),其 `Android/data|obb/<pkg>`
  下的勾选项标记 protected、跳过
- 二次确认:清理前弹窗显示项数与预计释放空间,大文件属中等风险默认不勾选

## 已知限制 / 未做(MVP 之外)

- **方案二(Shizuku + Agent + JNI)、方案三(完全 Root 深度清理 `/data/tombstones`、
  `/data/ota_package`、`/data/dalvik-cache`)** 未实现
- **重复文件为「按大小预筛」候选**,未做 MD5 全量校验(过 adb 读全盘太慢)
- **固定 maxdepth=6**:深于 6 层的缓存内容不计入(可调大,但更慢)
- 大文件陈旧度用 mtime(Android 多 `noatime`,atime 不可靠)
- 扫描用 one-shot `adb shell`(单条大命令,fork 开销可忽略);持久 shell 为可选优化
