# 通用后端接入

新版前端已有通用电路入口，但旧后台进程不会因磁盘源码更新自动升级。仅更新 EXE 或源码，仍可能连到只支持 RC 的旧服务。

本机通用服务地址为 http://127.0.0.1:8766，使用独立的 backend/runs-general 保存新结果。旧 RC 服务和历史数据保持可用。启动入口：

```powershell
powershell -ExecutionPolicy Bypass -File D:\GitHub\circuit-sim\backend\start_general_backend.ps1
```

桌面配置在 %LOCALAPPDATA%/CircuitSim/config.json，将 backend_url 设为 http://127.0.0.1:8766。当前电脑已经设置，桌面端口为 18766。打开 D:\CircuitSim-General.exe 或交付目录中的 CircuitSim.exe，选择“通用电路”。旧 D:\CircuitSim.exe 是 RC 版本，保持原文件以免覆盖正在运行的程序。

健康接口同时声明 api_versions 和 templates，明确区分服务程序版本与 v1/v2 输入契约。通用电路使用 /api/v2/parse、/preview、/runs；仍兼容 RC v1。

启动仅检查端口与必要依赖，不执行完整回归。拓扑、参数范围和仿真数值完整性检查保留。桌面程序及后端需分别运行；关闭后端窗口会停止服务。
