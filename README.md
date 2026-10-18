# 0.4.0 更新

前端适配新版通用后端，新增 [AI 电路设计助手](frontend/AI_DESIGN_ASSISTANT.md)：普通语言或图片输入，模型提出连接与参数建议，用户用是／否确认后预检和提交。启动通用后端使用 `backend/start_general_backend.ps1`（8766）；桌面与开发代理的新默认地址也为 8766，已有桌面配置保留。

# Circuit Sim · 电路仿真工作台

文字或电路截图 → 整理电路结构 → 逐项核对连接与参数 → 真实 Cadence / Spectre 仿真 → 对比曲线、独立曲线和报告。

已加入通用电路 v2：电阻、电容、电感、二极管、独立源、理想运放、导线，并扩展 BJT（NPN/PNP）、四端 PMOS 和四类线性受控源；支持 OP/DC/AC/TRAN、参数族、Y 参数提取、独立等效仿真与曲线误差比较。在输入页选择“通用电路”，可输入自然语言、上传电路截图，或从连接描述与示例开始。文字和图片使用用户配置的 AI 服务整理为候选电路，疑问补充及后端预检通过后，仍须确认才能仿真。完整用法见 [通用电路 v2](backend/docs/通用电路_v2.md) 和 [晶体管与二端口研究](backend/docs/晶体管与二端口研究.md)。本次晶体管与研究流程需使用当前源码或重新构建桌面版。

## Windows 桌面版

已有桌面版本可从本仓库的 **Releases** 下载 `CircuitSim.exe`，双击打开独立窗口。EXE 包含界面与 Python 运行时，使用系统 Microsoft Edge WebView2；真实后端需另行启动，Cadence/Virtuoso/Spectre 及许可证不包含在 EXE 中。0.3.0 的源码、EXE、网页构建、界面截图及验证记录一同发布。

从当前源码构建桌面版：

```powershell
powershell -ExecutionPolicy Bypass -File desktop/build.ps1
```

默认产物为 `desktop/release/CircuitSim.exe`，配置、系统要求和开发步骤见 [桌面版说明](desktop/README.md)。

## 项目组成

| 目录 | 内容 |
|---|---|
| [frontend](frontend/README.md) | React + TypeScript 界面、题目规划与后端契约适配 |
| [backend](backend/README.md) | FastAPI 服务、Cadence/Spectre 远程任务、结果校验和报告 |
| [desktop](desktop/README.md) | Windows 独立窗口、接口转发和 EXE 构建 |
| [backend/contracts](backend/contracts) | TaskSpec、结果与 OpenAPI 契约 |
| [backend/docs](backend/docs) | 验收材料和回归摘要 |

## 启动

在一个 PowerShell 窗口启动后端：

```powershell
cd D:\GitHub\circuit-sim\backend
.\setup_backend.ps1       # 首次安装或换电脑时执行，创建 .venv-local
.\start_backend.ps1       # 本机 http://127.0.0.1:8765
```

在另一个窗口启动前端：

```powershell
cd D:\GitHub\circuit-sim\frontend
npm install
npm run dev
```

打开 http://localhost:5173 。先确认顶栏显示“后端在线”，再填入示例题目、解析、检查参数并点击确认。离线演示模式有明确标注，其公式曲线不属于真实仿真证据。

## M1～M5 工作流程

| 里程碑 | 输入 → 工作 → 交付 | 验收门槛 |
|---|---|---|
| M1 固定电路 | 固定 RC → 真实建图、网表、仿真、截图 → 首次运行证据 | 真实端到端成功，结果可追溯 |
| M2 参数化 | 两组参数 → A/B/A 重复运行、完整脉冲、失败注入 → 回归记录 | 13 阶段、18 项数值检查、重复稳定、失败证据完整 |
| M3 接口接入 | API v1.0 → 前端确认、提交、轮询、工件下载 → 可操作界面 | 严格 TaskSpec、统一状态与错误、工件属于同一任务 |
| M4 题目到报告 | 有单位的文字条件 → 标准 R/C 推导、预检、用户确认 → 实测作答 | 题目条件可核对；确认前零提交；报告只引用本次证据 |
| M5 演示验收 | 单元/接口/浏览器检查 + 真实成功/失败回归 → 验收记录与冻结核对 | 清楚标识真实运行、历史证据和测试夹具；契约哈希一致 |

详细实现与证据见 [后端 README](backend/README.md)、[前端 README](frontend/README.md)、[本轮完善与验收记录](backend/docs/M1_M5_完善与验收.md)。

## RC 题目模式范围（v1）

- 一阶 RC 低通；支持有单位的显式 R/C，或按明确截止频率搜索 E24 电阻与常用电容组合。
- 确认页可编辑电平、周期、脉宽、上升/下降时间、延迟、AC 范围与点数、瞬态终点和最大步长。
- 前端规则只提取支持的明确条件；其余条件仍需用户核对。其他拓扑使用通用电路模式，支持从自然语言提取已知元件、连接和分析要求；仅给设计目标时仍需补充拓扑与参数，不自动保证方案正确。
- 截图先通过用户配置的视觉服务转成文字；后端 `/parse` 仅接受 `{text}`。
- 后端连接配置在 `backend/config.local.json`，本机密钥在 `backend/.local-ssh/`，均不提交 Git。换电脑时重建 Python 环境和本机 SSH 认证。

## 验证

```powershell
cd D:\GitHub\circuit-sim\frontend
npm test
npm run build
cd ..\backend
.\.venv-local\Scripts\python -m pytest tests -q
.\.venv-local\Scripts\python tools\verify_release.py
```

真实回归会使用服务器上的 Cadence 许可证。执行方法和浏览器验收见本轮验收记录；不要同时启动多个服务实例指向同一个 `runs/` 目录。

## 发布产物

Git 仓库保存源码、测试、说明和验收摘要。已有 Release 提供 Windows EXE、前端静态构建包、仿真运行证据包、使用说明与 SHA-256 校验清单；发布包与本轮源码更新的验收范围分别以对应版本说明为准。

运行证据包解压到项目根目录后会恢复 `backend/runs/`，可用于已有的离线证据回归。依赖目录、虚拟环境、缓存、本机私有配置和 SSH 密钥由 `.gitignore` 管理。
