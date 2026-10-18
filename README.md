# 电路仿真助手 · CircuitSim

面向 Windows 桌面的 RC 低通电路仿真助手：题目输入和图片识别、参数推导与确认、任务进度、原理图与波形、指标和实验报告。

## 桌面版下载

从本仓库的 **Releases** 下载 `CircuitSim.exe`，双击打开独立窗口。EXE 已包含界面与 Python 运行时，使用系统 Microsoft Edge WebView2。

当前桌面版通过 `http://127.0.0.1:8765` 连接后端，后端需要单独启动；连接失败时进入明确标注的演示模式。Cadence/Virtuoso/Spectre 及其授权不包含在桌面 EXE 中。

## 项目组成

| 目录 | 内容 |
| --- | --- |
| [frontend](frontend/README.md) | React + TypeScript 界面、题目规划与后端契约适配 |
| [backend](backend/README.md) | FastAPI 服务、Cadence/Spectre 远程任务、结果校验和报告 |
| [desktop](desktop/README.md) | Windows 独立窗口、接口转发和 EXE 构建脚本 |
| [backend/contracts](backend/contracts) | TaskSpec、结果与 OpenAPI 契约 |
| [backend/docs](backend/docs) | 验收材料和回归摘要 |

## 开发与构建

前端：在 `frontend` 执行 `npm ci`、`npm run dev`。`npm test` 运行前端回归检查，`npm run build` 生成静态界面。

后端：参考 [后端说明](backend/README.md)，创建本机 Python 环境并安装 `requirements-dev.txt`；根据 `config.example.json` 创建本机配置，再启动 `serve.py`。真实仿真需要可用的远程 EDA 环境。

Windows EXE：在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File desktop/build.ps1
```

产物默认位于 `desktop/release/CircuitSim.exe`。详细系统要求、配置位置和开发步骤见 [桌面版说明](desktop/README.md)。

## 发布产物

Git 仓库保存源码、测试、说明和验收文档。Release 提供 Windows EXE、前端静态构建包、仿真运行证据包、使用说明与 SHA-256 校验清单。依赖目录、虚拟环境、缓存和本机私有配置由各目录的 `.gitignore` 管理。

运行证据包解压到项目根目录后会恢复 `backend/runs/`，可用于后端已有的离线证据回归；不需要为此重新执行远程仿真。
