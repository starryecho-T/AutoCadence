# AutoCAD 后端启动

运行 `backend/start_general_backend.ps1`，默认端口 8766，新任务保存在 `backend/runs-general`。`/health` 中应显示 `name: AutoCAD` 和 `build: 0.5.0`。旧进程不会因磁盘更新自动重新加载代码，启动脚本会识别并提示版本不一致。

桌面程序为 `AutoCAD.exe`，配置位于 `%LOCALAPPDATA%/AutoCAD/config.json`。本机配置后端 8766、桌面端口 18766；更新程序迁移已有配置和模型设置。开发源码入口为 `D:\GitHub\AutoCAD`，该路径为兼容本机已安装依赖的目录入口。

本机已关闭旧桌面窗口并启动 `D:\2\AutoCAD.exe`，旧 EXE 已移至本次更新备份目录，避免误开旧版。
