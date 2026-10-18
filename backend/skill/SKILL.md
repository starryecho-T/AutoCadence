# VAI Virtuoso 仿真 Skill（API v1.0）

驱动本地 VAI 后端，完成「读题 → 参数确认 → 真实 Cadence 仿真 → 证据报告 → 作答」全流程。后端纯确定性、无任何模型调用；本 skill 供应用内 agent（用户自配 API）使用，负责读题、推导参数与最终作答。

## 0. 硬性规则（违反即视为无效作答）

1. **只用同一次运行的证据**：数值引用 `metrics.json`、图片/报告引用该 `run_id` 的 `artifacts[].url`，绝不跨运行拼装、不用 fixture 冒充实时结果。
2. **不改写数值**：截止频率、电压等一律原样引用 metrics，可加单位换算但不得修正/估算。
3. **只有 `status == "succeeded"` 才算通过**；`failed` 时展示 `error.code / error.stage / error.message` 三元组并保留日志链接，不重试同参数任务。
4. **必须先确认再提交**：`/parse` 与推导结果都只是候选（`requires_confirmation=true`），须经用户确认才 `POST /runs`；题目含额外激励条件（周期/幅值等）时必须逐项设置，不得沿用默认。
5. 用户 API key 只保存在产品应用内；后端永不需要、也不得请求该 key。

## 1. 前置检查

```python
from skill.vai_client import VaiClient
client = VaiClient('http://127.0.0.1:8765')          # 可选 token: VaiClient(base, token='...')
assert client.health()['status'] == 'ok'
```

端点速查：`GET /health`、`GET /api/v1/capabilities`、`POST /api/v1/parse`、`POST /api/v1/runs`（202）、`GET /api/v1/runs`、`GET /api/v1/runs/{id}`、`GET /api/v1/runs/{id}/artifacts/{artifact_id}`、`GET /openapi.json`、`GET /docs`。契约：`contracts/task.schema.json`、`contracts/result.schema.json`。

## 2. 工作流

**步骤 1 — 题目分类**
- 含明确 R、C 数值 → `POST /api/v1/parse`（`{"text": 题目}`），取返回 `task` 候选；关注 `missing_fields` / `defaults_applied` / `warnings`。
- 只给行为指标（如"截止频率约 1 kHz"）→ 用设计规则推导（见 §3）。注意：R/C 缺失时 parse 会提前返回（`warnings` 为空），脉冲等额外激励条件由 agent 直接从题目文本提取——这正是产品中用户自配 API 的 agent 的职责。
- 出现 高通/带通/运放/图片附件 等关键词 → `supported=false`，直接告知"当前仅支持一阶 RC 低通文字题目"。

**步骤 2 — 组装 TaskSpec 并请求确认**

向用户展示完整参数表：R/C（含推导误差）、脉冲激励（幅值/周期/脉宽/沿/延迟）、AC 范围、瞬态终点与步长；标注所有默认项与警告。用户编辑确认后进入步骤 3。

**步骤 3 — 提交与轮询**

```python
run = client.submit(spec)                 # 202, status=queued；422 则按 details 修参数并回到步骤 2
run = client.wait_run(run['run_id'], timeout=360)   # 内部每 1.5 s 轮询至终态
```

**步骤 4 — 作答（引用证据）**

从 `run['metrics']` 取数值、按 `filename` 找 `artifacts` 取 `report_html` / `waveform` / `schematic`：

```python
report_html = client.artifact_bytes_by_filename(run, 'report.html')
```

答案模板：
> 采用 R={r}、C={c} 的一阶 RC 低通。Spectre 实测 -3 dB 截止频率 {fc} Hz（理论 {fc_theory} Hz，误差 {err}%）；时间常数 τ 下输出达 {vout_tau} V。脉冲响应覆盖完整周期（升沿×{r_n}、降沿×{f_n}）。原理图/波形截图与完整数值报告见本次运行 {run_id} 的 report.html。

## 3. 设计规则（行为指标 → 合法 TaskSpec）

**截止频率 → 标准值**：`derive_rc_from_cutoff(fc_hz)` 在 E24 电阻 × 常用电容中选 `|fc_实际/fc|-1|` 最小的组合（默认 ≤2% 误差；平局时偏向 10 kΩ 附近的电阻档），返回 `r_ohm/c_f/fc_achievable/error`。需向用户说明标准值舍入误差。

**必须满足的约束**（`precheck_spec(spec)` 本地预检，最终以服务端 422 为准）：

| 约束 | 规则 |
|---|---|
| 元件范围 | R ∈ [10, 1e6] Ω；C ∈ [1p, 1m] F |
| AC 覆盖 | `start ≤ fc/5` 且 `stop ≥ fc*5`；点数 ≤ 1500 |
| 瞬态覆盖 | `stop ≥ delay + 2.05×period`（保证 ≥2 完整脉冲周期）|
| 最大步长 | `max_step ≤ min(τ/20, period/200, width/20)` |
| 点数预算 | `stop/max_step ≤ 60000` |
| 脉冲时序 | `rise + width + fall < period`；`high > low` |

推导后按题目条件覆盖默认激励；题目未给的项用 capabilities 默认值并标注。

## 4. 失败码与处置

| code | 含义 | 处置 |
|---|---|---|
| `VALIDATION_ERROR` (HTTP 422) | TaskSpec 违反 §3 约束 | 按 details 修参数，重新确认 |
| `QUEUE_FULL` (HTTP 429) | 队列上限 20 | 等当前运行完成后重提 |
| `ENVIRONMENT_MISSING` | 服务器 Cadence 路径不可用 | 联系服务器管理员，勿重试 |
| `NETLIST_MISMATCH` | 网表与请求参数不符 | 提 bug，附 run_id |
| `SPECTRE_ERRORS` | 仿真器报错（审计非 0 错误） | 查看 artifacts 中 spectre 日志 |
| `STAGE_TIMEOUT` / `PROCESS_FAILED` | 阶段超时/进程失败 | 换 run_id 重提一次；复现则提 bug |
| `PROTECTED_FILE_CHANGED` | 保护文件哈希变化（安全熔断） | 立即停止使用并上报 |
| `INTERRUPTED` | 后端重启打断 | 重新提交新任务 |

## 5. 运行产物（succeeded 时全部存在）

`schematic_window.png`、`waveform_window.png`、`schematic_native.png`、`waveform_native.png`（真实 Cadence 截图，经画布像素校验）、`input.scs`、`metrics.json`、`report.html`、`report.md`、`stages.json`、`spectre.out`、`protection.json`。全部带 SHA-256 索引，经 artifacts 端点下载校验。

## 6. 完整示例

见 `tools/m4_demo.py`：行为类题目（"截止频率约 1 kHz 的音频抗混叠 RC 低通，0→2 V、周期 4 ms、脉宽 2 ms 脉冲验证"）→ 推导 R=16 kΩ/C=10 nF → 预检 → 确认 → 真实运行 → 引用 metrics 作答。该脚本即本 skill 的参考实现。
