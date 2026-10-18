# Windows 桌面版

目标：双击 `AutoCadence.exe` 后打开“AutoCadence”独立窗口。EXE 包含 Python 运行时与已构建的 React 界面，使用系统 Microsoft Edge WebView2 显示界面，用户无需安装 Python、Node.js 或启动前端开发服务。

当前版本封装 RC 与通用电路前端，连接单独启动的现有仿真后端。后端不可达时显示明确的演示模式；不会把本地公式结果当成真实仿真。

## 使用

1. 双击 `release/AutoCadence.exe`。
2. 后端默认连接 `http://127.0.0.1:8766`；RC 使用 v1 接口，通用电路需要支持 v2 的后端。
3. 后端启动后，在输入页点击“重新连接”。
4. 结果页点击“保存报告”，选择 HTML 或 Markdown 文件的保存位置。

窗口关闭后，桌面程序的本地服务一并退出。重复启动会尝试激活已打开的窗口。

系统要求：64 位 Windows 10/11、.NET Framework 4.8 和 Microsoft Edge WebView2 Runtime。若目标电脑缺少 WebView2，可通过 [Microsoft 官方页面](https://developer.microsoft.com/microsoft-edge/webview2/) 安装 Evergreen Runtime。

## 配置与数据

启动时在 `%LOCALAPPDATA%/AutoCadence/` 创建应用数据目录：

- `config.json`：后端地址及桌面服务端口。
- `WebView2/`：窗口自己的浏览器配置，包括保存的 AI 识别设置。
- `desktop.log`：启动诊断日志。

默认配置：

```json
{
  "backend_url": "http://127.0.0.1:8766",
  "desktop_port": 18766
}
```

修改配置后重新启动 EXE。桌面服务仅监听 `127.0.0.1`。固定端口让 localStorage 在重启后继续可用；更改 `desktop_port` 会使用新的网页存储来源，需要重新填写识别设置。

开发和自动检查可使用 `AUTOCADENCE_DATA_DIR` 指定隔离数据目录，或用 `AUTOCADENCE_BACKEND_URL` 覆盖后端地址。

## 从源码生成 EXE

在 Windows 安装 Python 3.12+ 与 Node.js 20+。首次先在 `frontend` 运行 `npm ci`，然后从项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File desktop/build.ps1
```

脚本创建独立 Python 环境、安装固定版本桌面依赖、检查并构建前端、运行桌面服务测试，最后用 PyInstaller 生成 `desktop/release/AutoCadence.exe`。可以用 `-Python` 指定 Python 路径，用 `-OutputDirectory` 指定输出目录。

源码调试：

```powershell
desktop/.venv/Scripts/python.exe desktop/main.py
```

## 后端接入边界

- `/health`、`/openapi.json` 和 `/api/*` 原样转发到配置的后端，保持 JSON、图片、报告与错误状态码。
- 后端代码目前未打入 EXE，也未由本程序自动启动。
- 获得后端代码后，再接入后端进程启动、就绪检查、仿真依赖打包与随窗口退出的清理逻辑。
- 当前产物为免安装单文件版本；安装向导、签名和自动更新可在后端集成后补充。

实现参考：[pywebview Windows 依赖](https://pywebview.flowrl.com/guide/installation.html)、[pywebview 打包指南](https://pywebview.flowrl.com/guide/freezing.html)、[PyInstaller 构建选项](https://pyinstaller.org/en/stable/usage.html)。
