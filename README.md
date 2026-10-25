# AutoCadence

AutoCadence 是面向电路题目的桌面设计与仿真应用。普通语言或图片输入 → AI 给出连接和参数建议 → 用户选择是／否 → 核对电路 → Cadence / Spectre 仿真 → 独立曲线与报告。

当前版本 **0.7.1**。窗口、网页、EXE、桌面配置目录、文档与报告统一使用 AutoCadence。侧栏显示具体任务名称、元件和分析摘要，底部显示版本号。

新建任务统一进入通用电路输入，支持文字、截图和连接描述；已移除独立的 RC 低通题目入口。RC 电路也通过统一入口提交。后端未连接时可准备题目，连接后再预检和仿真。

## 使用

双击 `AutoCadence.exe`，内置本机后端自动启动，无需安装 Python 或另开启动脚本。在左侧“仿真服务器”默认已填入服务器地址 `101.6.64.74` 和 SSH 端口 `35167`，填写自己的账号和密码，也可选择本机私钥；点击“连接并保存”。首次连接需核对服务器指纹，程序自动探测 Cadence 环境路径，未找到时可在高级设置补全。AI 服务独立在“AI 设置”中配置。

每人在自己的 Windows 电脑上使用。密码默认仅在本次后端会话内使用；选择“记住密码”后由 Windows 当前用户加密保存，可随时清除。SSH 密码不进入浏览器存储、AI 请求、仿真输入包或报告。服务器地址和端口仍可修改；已有连接优先使用保存的值。EXE 不包含开发者的账号、私钥或密码。服务器需已安装并授权 Cadence / Spectre，详见 [服务器连接说明](backend/SSH_SETUP.md)。

已有桌面配置和 AI 设置保留。开发时仍可单独运行 `backend/start_general_backend.ps1`，桌面程序复用同版本、位于 `127.0.0.1:8766` 的后端。

原理图现在为双端并联电路绘制母线，为串联回路绘制闭合连接，其余电路使用每个端子独立的连线接入对应节点母线。交叉线只在有接点的位置相连；实际导线的端子及 Cadence 网表必须与确认的电路匹配后才运行仿真。

## 组成

- `frontend/`：React + TypeScript 界面、AI 设计建议、结果与曲线。
- `backend/`：FastAPI、通用电路解析、Cadence / Spectre 调用及验证。
- `desktop/`：WebView2 独立窗口与 AutoCadence.exe 打包。

开发：在 `frontend/` 安装依赖并运行 `npm run dev`。桌面构建入口为 `desktop/build.ps1`。详见 [桌面说明](desktop/README.md)、[AI 设计助手](frontend/AI_DESIGN_ASSISTANT.md)、[通用电路](backend/docs/通用电路_v2.md)。

## 结果问答

结果页提供“与 AI 讨论本次结果”。沿用用户的 AI 服务地址、密钥和文本模型，可分析成功或失败任务。点击发送后才读取该任务的电路、指标、各信号的原始数值统计、抽样点及必要日志；密钥只发给用户配置的模型服务，不发给仿真后端。对话按任务隔离，当前窗口会话内保留，支持取消、重试与清空。模型没有执行或修改电路的权限。

后端新增只读 `GET /api/v2/runs/{run_id}/ai-context`。统计使用原始导出数据，长波形只发送抽样点；未读取或受上下文限制的文件会明确列出。

## 验证

SSH 更新针对性验证了密码登录、错误密码、服务器指纹确认、Windows 加密保存和凭据隔离；原有服务器私钥登录与 PMOS 真实仿真通过。发布前检查前端构建和无旧配置的 EXE 启动。历史 PMOS 截图裁剪误判和运放直流反馈提示的修复均保留。

## 2026-10-25 更新与问题记录

本次更新：新增 NMOS 器件端到端支持（模型卡 `mos1 type=n`、analogLib `nmos4` 符号、端子电流 d/g/s/b、原理图符号、文本解析、标题与 AI 能力清单，示例 `nmos_id_vgs`）；后端 artifacts 哈希增量缓存、任务失败路径兜底、`DELETE /api/v{1,2}/runs/{id}` 取消排队任务、队列上限检查移入锁内、保存连接时不再长时间持有全局锁；前端波形 JSON 路径统一降采样、独立曲线懒渲染、轮询失败指数退避重试（1.5s→3s→6s）、根级与卡片级 ErrorBoundary、波形加载失败重试按钮。

### 问题记录与解决方法

**1. SSH 下载结果包被静默截断（严重，已修复）**

- 现象：远端仿真全部成功，本地解包报 `Compressed file ended before the end-of-stream marker was reached`，任务在 download 阶段失败。
- 根因：`backend/vai_backend/ssh_transport.py` 的输出排空循环以 `exit_status_ready()` 作为退出条件。课程服务器的老版本 OpenSSH 会在 stdout 尾部数据到达之前先发出 exit-status，循环提前退出而 returncode 仍为 0。实测远端 354,063 字节的归档只传回 212,992 字节，且每次都复现。
- 解决：退出条件必须等待 channel EOF（或 closed）且接收缓冲排空，之后才取退出码。课程服务器的老版 OpenSSH 会在 stdout 尾部数据到达前先发出 exit-status，`exit_status_ready()` 单独作为退出条件会提前 break。本地测试用的内嵌 paramiko 服务端时序正常、不触发此 bug，因此此前未暴露；修复后用真实服务器对照验证，流式传输与远端落盘字节数完全一致。教训：针对传输层时序问题，验收必须在真实目标服务器上做大文件回归。当前代码采用条件 `exit_status_ready() and (eof_received or closed) and 缓冲排空`。

**2. GitHub 无法访问时的代码同步（已处理）**

- 现象：`git fetch` 直连与常见本地代理端口（7890/10809/1080，http 与 socks5）均连接失败（连接重置或超时）。
- 解决：利用本地已缓存的 `origin/main` 引用完成同步——对 origin/main 全部 172 个文件逐个 `git hash-object` 与磁盘比对，165 个字节一致，唯一差异是上述 ssh_transport 修复（6 个中文名文档被 `core.quotepath` 转义误报为缺失，实际存在且一致）；随后 `git checkout -f -B main origin/main` 对齐分支、恢复修复。网络恢复后重新 fetch 即可。

**2.1 推送被拒：远端出现新提交（已整合）**

- 现象：首次 `git push` 被拒（non-fast-forward）。此时网络已恢复——被拒不是连接问题，而是远端已有新提交 `5c8ff7a`（新增 CMN018 器件与结果视图改进，且独立修复了同一个 SSH 截断 bug、加入了 NMOS 支持）。
- 整合：`git rebase origin/main` 后逐文件解决 17 个重叠文件冲突，原则是远端 CMN018 逻辑全保留、两边 NMOS 取并集（NMOS 类与 model_types 映射用远端的继承式设计，保留本地新增的 MOS1Model 阈值符号校验器和 `bulk` 引脚标签），ssh 排空条件采用远端等价写法；两处测试断言随合并后语义适配（极性错配的报错文案、nmos+pmos 混合电路的「CMOS 电路」标题族）。整合后后端 115 项、前端 55 项测试全过，并在真实服务器复测 RC 与 NMOS 仿真均成功后推送。教训：推送被拒先 `git fetch` 看远端新增了什么、是否与本地改动语义重叠，不要直接 force push。

**3. NMOS 真实服务器验收（通过）**

- 需在真实 Cadence 环境确认的点均已验证：analogLib `nmos4` 符号存在且端子为 D/G/S/B；端子电流按小写 `d/g/s/b` 导出；`mos1 type=n` 教学模型正常收敛。
- 物理正确性：NMOS 栅压 DC 扫描（0→3.3V，W/L=10µm/1µm，vto=0.7V）实测 Id-Vgs 与 MOS1 平方律精确吻合——阈值以下完全截止，Vgs=1V 时 Id=0.048mA、Vgs=3.3V 时 Id=3.603mA，与含沟道长度调制（lambda=0.02）的理论值 3.60mA 一致，region=2（饱和区）。RC 示例回归仿真同步复测通过。

**4. 已知事项**

- `backend/contracts/openapi.json` 是静态快照，尚未包含新增的取消端点 `DELETE /runs/{id}`，下次契约刷新时同步。
- artifacts 增量缓存以 `(mtime_ns, size)` 为缓存键，同大小同纳秒时间戳的写入存在理论上的误判窗口（现有测试用显式 `os.utime` 规避）。
- 桌面 `AutoCadence.exe` 内置后端仍是打包时的 0.7.1 代码，要获得上述修复与 NMOS 支持需重新 `desktop/build.ps1` 打包；`desktop/local_backend.py` 的版本白名单 `('0.7.0','0.7.1')` 需随新版本号一并更新。
