# AutoCadence 后端启动

运行 `backend/start_general_backend.ps1`，默认端口 8766，新任务保存在 `backend/runs-general`。`/health` 中应显示 `name: AutoCadence` 和 `build: 0.7.0`。旧进程不会因磁盘更新自动重新加载代码，启动脚本会识别并提示版本不一致。

桌面程序 `AutoCadence.exe` 已内置本机后端。普通使用直接打开 EXE，在“仿真服务器”填写自己的连接信息，无需运行启动脚本。桌面配置位于 `%LOCALAPPDATA%/AutoCadence/config.json`，连接配置位于同目录的 `connection.json`。更新时保留已有配置和模型设置。

启动脚本用于开发或单独运行后端。桌面程序复用同版本的独立后端；内置后端的任务保存在 `%LOCALAPPDATA%/AutoCadence/runs`，独立后端继续使用其自己的任务目录。详见 [SSH 连接说明](SSH_SETUP.md)。
