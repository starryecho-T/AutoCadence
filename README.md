# AutoCAD

AutoCAD 是面向电路题目的桌面设计与仿真应用。普通语言或图片输入 → AI 给出连接和参数建议 → 用户选择是／否 → 核对电路 → Cadence / Spectre 仿真 → 独立曲线与报告。

当前版本 **0.5.0**。窗口、网页、EXE、桌面配置目录、文档与报告统一使用 AutoCAD。侧栏显示具体任务名称、元件和分析摘要，底部显示版本号。

## 使用

启动 `backend/start_general_backend.ps1`，再打开 `AutoCAD.exe`。默认后端地址为 `http://127.0.0.1:8766`；AI 服务在应用设置中配置。已有桌面配置和 AI 设置在首次使用新名称时复制保留。

原理图现在为双端并联电路绘制母线，为串联回路绘制闭合连接，其余电路使用每个端子独立的连线接入对应节点母线。交叉线只在有接点的位置相连；实际导线的端子及 Cadence 网表必须与确认的电路匹配后才运行仿真。

## 组成

- `frontend/`：React + TypeScript 界面、AI 设计建议、结果与曲线。
- `backend/`：FastAPI、通用电路解析、Cadence / Spectre 调用及验证。
- `desktop/`：WebView2 独立窗口与 AutoCAD.exe 打包。

开发：在 `frontend/` 安装依赖并运行 `npm run dev`。桌面构建入口为 `desktop/build.ps1`。详见 [桌面说明](desktop/README.md)、[AI 设计助手](frontend/AI_DESIGN_ASSISTANT.md)、[通用电路](backend/docs/通用电路_v2.md)。

## 本轮验证

16 项前端相关测试、20 项后端编译和标题测试、5 项桌面代理测试及浏览器确认流程通过。RC 高通回路、PNP 多节点、PMOS 多端器件的真实仿真及连接网表核对通过。旧任务的原始截图作为历史证据保留，新任务使用完整布线。
