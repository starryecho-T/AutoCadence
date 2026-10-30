# AutoCadence

AutoCadence 是面向电路题目的桌面设计与仿真应用。普通语言或图片输入 → AI 给出连接和参数建议 → 用户选择是／否 → 核对电路 → Cadence / Spectre 仿真 → 独立曲线与报告。

当前版本 **0.7.5**。窗口、网页、EXE、桌面配置目录、文档与报告统一使用 AutoCadence。侧栏显示具体任务名称、元件和分析摘要，底部显示版本号。

新建任务统一进入通用电路输入，支持文字、截图和连接描述；已移除独立的 RC 低通题目入口。RC 电路也通过统一入口提交。后端未连接时可准备题目，连接后再预检和仿真。

## 使用

双击 `AutoCadence.exe`，内置本机后端自动启动，无需安装 Python 或另开启动脚本。在左侧“仿真服务器”默认已填入服务器地址 `101.6.64.74` 和 SSH 端口 `35167`，填写自己的账号和密码，也可选择本机私钥；点击“连接并保存”。首次连接需核对服务器指纹，程序自动探测 Cadence 环境路径，未找到时可在高级设置补全。AI 服务独立在“AI 设置”中配置。

**0.7.3 起，第一次仿真 NMOS/PMOS 题目前必须配置模型文件**：打开“仿真服务器 → 高级设置”，在 CMN018 主模型文件里填服务器上的绝对路径，例如 `/data/home/<你的学号>/cmn018_models/cmn018_gp2a_5v_v1d4.scs`（同目录还需有 `cmn018_gp2a_5v_v1d4_usage.scs`）。服务器上每位用户的家目录需要各传一份模型文件（共享服务器可由管理员放到公共只读目录供所有人使用）；未配置时 MOS 仿真会在预检报 `CMN018_NOT_CONFIGURED`。R/C/L、二极管、BJT 题目不受影响；教学近似可显式指定 `generic_nmos`/`generic_pmos`。

每人在自己的 Windows 电脑上使用。密码默认仅在本次后端会话内使用；选择“记住密码”后由 Windows 当前用户加密保存，可随时清除。SSH 密码不进入浏览器存储、AI 请求、仿真输入包或报告。服务器地址和端口仍可修改；已有连接优先使用保存的值。EXE 不包含开发者的账号、私钥或密码。服务器需已安装并授权 Cadence / Spectre，详见 [服务器连接说明](backend/SSH_SETUP.md)。

已有桌面配置和 AI 设置保留。开发时仍可单独运行 `backend/start_general_backend.ps1`，桌面程序复用同版本、位于 `127.0.0.1:8766` 的后端。

原理图现在根据连接拓扑选择布局：双端并联电路绘制母线，串联回路绘制闭合连接；接地的电阻主干和对地支路采用从左到右的电源梯形布局，电容自动接在其实际节点。其他电路仍使用每个端子独立接入对应节点母线的通用布局。交叉线只在有接点的位置相连；实际导线的端子及 Cadence 网表必须与确认的电路匹配后才运行仿真。

## 受控开关

通用电路现支持四端电压控制开关（Cadence analogLib/switch，Spectre relay）。在示例中选择「10 MHz 受控开关与电源去耦」，即可看到以 100 ns 周期的 PULSE 电压源驱动开关、观察 A/B 两点电压的完整输入。连接描述也支持 S1 通路正 通路负 控制正 控制负 [断开阈值 闭合阈值 断开电阻 闭合电阻]。0.7.5 EXE 文件在 desktop/release/AutoCadence.exe。

## 自动布局规则

先把元件和端子整理为已校验的节点图，再识别接地供电梯形电路：左侧放电源，串联电阻沿上方从左到右排列；与主干节点相接的电阻或电容垂直下接公共地线。开关负载作为同一节点的串联支路，控制脉冲源放在右侧，控制端和功率通路分别接线。电容的位置由其真实节点决定，与输入元件顺序无关；A 点、B 点、电阻中点及多电容分配均使用相同规则。不能确定主干或遇到其他器件时退回原有布局，不推测连接；生成后逐端检查并对照 Virtuoso 网表。

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

**6. NMOS/PMOS 默认改用 CMN018 工艺模型（0.7.3，2026-10-26）**

- 应用户要求：组件类型 `nmos`/`pmos` 与连接描述 M 行的缺省模型从 generic 教学模型改为 CMN018 直接模型 `nch`/`pch`，即"要用 NMOS/PMOS 就使用服务器上的模型文件"。`cmn018_model_file` 未配置时远端预检明确报 `CMN018_NOT_CONFIGURED`；`generic_nmos`/`generic_pmos` 仍可显式指定作为教学近似。capabilities 新增 `default_models` 提示，AI 设计建议与格式帮助同步。
- pch 真机验收通过（W/L=10u/0.18u，tt 角，源接 1.8V、漏经 0V 电源接地）：Vgs=-1.8V 时 Id=-2.58mA，约为 nch（5.98mA）的 1/2.3，符合空穴迁移率比；Vgs→0 单调截止。打包 EXE 复测缺省模型任务与开发后端结果一致。
- 版本升至 0.7.3（同前 11 处），EXE 重新打包并已更新本机 `D:\AutoCadence.exe`；GitHub Release 仍为 v0.7.2，需要时可再发 0.7.3。注意：保存的连接若在界面里改回密码认证且未输密码，仿真会报 `SSH_PASSWORD_REQUIRED`，重新选择私钥并保存即可（本次即因此重存）。

**5. 0.7.2 发布与 CMN018 真机验收（2026-10-26）**

- 版本号提升至 0.7.2（`/health` build、桌面白名单、启动脚本、侧栏、EXE 版本资源共 11 处），重新打包并通过真实仿真验收后发布 GitHub Release v0.7.2（EXE + 源码包 + 前端包 + 校验文件）。
- 打包 EXE 曾在旧 0.7.1 后端存活时因白名单直接复用旧后端，无法验证新版本；验证新 EXE 前需先退出旧实例。本机旧 EXE（`D:\AutoCadence.exe` 与 `desktop/dist/` 各一）已删除，替换为从 Release 下载并校验 SHA256 的 0.7.2。
- CMN018 模型卡（`model/cmn018_gp2a_5v_v1d4.scs` 及 usage 文件，即 NMOS 等器件的工艺参数文件）已上传至服务器 `/data/home/<user>/cmn018_models/`，并在连接高级设置中配置 `cmn018_model_file`。随后用打包 EXE 完成 `nch` NMOS 直流扫描验收：Vth≈0.43V 开启，Vgs=1.8V 时 Id=5.98mA（≈0.6mA/µm，符合 0.18µm 工艺电流密度），region=2 饱和区，validation PASS，模型卡哈希经 protection.json 审计且运行前后一致。

**4. 已知事项**

- `backend/contracts/openapi.json` 是静态快照，尚未包含新增的取消端点 `DELETE /runs/{id}`，下次契约刷新时同步。
- artifacts 增量缓存以 `(mtime_ns, size)` 为缓存键，同大小同纳秒时间戳的写入存在理论上的误判窗口（现有测试用显式 `os.utime` 规避）。
- 发布 0.7.2 时已重新打包桌面 EXE（含全部修复与 NMOS/CMN018 支持）；`desktop/local_backend.py` 的版本白名单现接受 0.7.0/0.7.1/0.7.2。开发机上若 `node` 不在 PATH，`desktop/build.ps1` 的前端步骤需改用 Electron 内置 Node（`ELECTRON_RUN_AS_NODE=1`）等价执行。
