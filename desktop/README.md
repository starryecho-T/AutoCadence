# Windows 桌面版

双击 `AutoCadence.exe` 打开独立窗口。EXE 包含 Python 运行时、React 界面及本机仿真后端，无需安装 Python、Node.js 或手动启动服务。实际电路仿真由用户自己的 Linux 服务器上的 Cadence / Spectre 执行。

## 首次使用

1. 打开 EXE，在左侧选择“仿真服务器”。
2. 默认服务器为 `101.6.64.74:35167`，填写自己的账号和密码，也可以使用本机私钥文件。地址和端口仍可修改，已保存配置优先。
3. 点击“连接并保存”。首次连接向管理员核对服务器指纹后确认。
4. 程序自动探测环境路径，未找到时打开高级设置补全。
5. 在“AI 设置”配置自己的模型服务，然后提交文字、图片或连接描述。

密码默认仅在本次后端会话内使用。勾选“记住密码”后使用 Windows 当前用户加密保存，可在设置中清除。应用只预填服务器地址和端口，不内置个人账号或凭据。每个用户需有可用的服务器账号及 Cadence 许可，详见 [服务器连接说明](../backend/SSH_SETUP.md)。

系统要求：64 位 Windows 10/11、.NET Framework 4.8 和 Microsoft Edge WebView2 Runtime。缺少 WebView2 时安装 [Microsoft Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。

## 配置与数据

当前用户的 `%LOCALAPPDATA%/AutoCadence/` 保存：

- `config.json`：本机后端地址及桌面服务端口。
- `connection.json`：服务器配置及可选的加密密码。
- `known_hosts`：确认过的服务器身份。
- `runs/`：由内置后端产生的任务、报告与结果。
- `WebView2/`：桌面浏览器配置及 AI 设置。
- `desktop.log`：启动诊断日志。

新安装默认后端 `http://127.0.0.1:8766`，桌面端口 `18765`；已有配置保留原端口。两项服务只监听本机。更改桌面端口会改变网页存储来源，需要重新填写 AI 设置。旧名称 AutoCAD、CircuitSim 的配置会在首次启动时迁移。

同版本的独立本机后端已运行时，桌面程序直接复用它，任务保存在该后端配置的目录；否则自动启动内置后端。请等待仿真完成再退出，关闭窗口会结束内置后端，复用的独立后端继续运行。重复启动会激活已有窗口。

开发检查可使用 `AUTOCADENCE_DATA_DIR` 指定隔离数据目录、`AUTOCADENCE_BACKEND_URL` 指定后端地址，或 `VAI_CONNECTION_FILE` 指定连接配置文件。

## 从源码生成 EXE

Windows 上安装 Python 3.12+ 与 Node.js 20+，在 `frontend` 执行 `npm ci`，然后在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File desktop/build.ps1
```

脚本安装依赖、检查并构建前端、运行桌面测试，生成 `desktop/release/AutoCadence.exe`。可用 `-Python` 指定 Python 路径、`-OutputDirectory` 指定输出目录。源码调试入口为 `desktop/.venv/Scripts/python.exe desktop/main.py`。

`/health`、`/openapi.json` 和 `/api/*` 转发到配置的后端，保留 JSON、图片、报告与错误状态码。当前产物为免安装单文件版本。
