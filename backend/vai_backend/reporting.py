"""Reports built from numeric run evidence and explicit screenshot filenames."""
from __future__ import annotations
import base64
import hashlib
import html
import json
from pathlib import Path

_IMAGES = (
    ('schematic_window.png', 'Virtuoso 原理图真实窗口截图'),
    ('waveform_window.png', 'ViVA 波形真实窗口截图'),
    ('schematic_native.png', 'Cadence 原理图原生导出（不是窗口截图）'),
    ('waveform_native.png', 'Cadence 波形原生导出（不是窗口截图）'),
)


def generate_report(task: dict, metrics: dict, evidence_dir: Path, run_id: str, warnings: list) -> None:
    root = Path(evidence_dir)
    root.mkdir(parents=True, exist_ok=True)
    esc = lambda value: html.escape(str(value), quote=True)
    warnings = [str(x) for x in warnings]
    images = []
    for filename, caption in _IMAGES:
        path = root/filename
        if not path.is_file():
            warnings.append(f'图像缺失：{filename}；本报告不将该项视为已验证。')
            continue
        data = path.read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError(f'Invalid PNG evidence: {filename}')
        images.append({'name': filename, 'caption': caption, 'data': base64.b64encode(data).decode('ascii'), 'sha256': hashlib.sha256(data).hexdigest()})
    checks = metrics.get('checks', [])
    status = metrics.get('validation_status', 'UNVERIFIED')
    if not checks or any(c.get('status') != 'PASS' for c in checks):
        status = 'UNVERIFIED' if not checks else 'FAIL'
    if any(not (root/name).is_file() for name, _ in _IMAGES[:2]):
        warnings.append('真实窗口截图不完整；数值 PASS 不代表图像交付通过。')
    task_json = json.dumps(task, ensure_ascii=False, indent=2, allow_nan=False)
    metric_json = json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=False)
    limitations = list(metrics.get('limitations', [])) + [
        '本报告只对应上述 run_id 的受支持 RC 低通实例，不代表任意电路自动设计能力。',
        '数值引用 Spectre 原始导出数据；瞬态参考由实际输入的分段线性精确 RC 递推计算。',
        '上升/下降时间由 10–90% 阈值交点除以 0.8 得到，测量受采样与文本精度约束。',
        '截图与原生导出均由执行阶段提供；报告不生成、拼接或重绘替代截图。',
    ]
    summary = [
        ('截止频率 / 理论 Hz', f"{metrics.get('fc_hz', '未验收')} / {metrics.get('fc_theory_hz', '未验收')}"),
        ('截止频率相对误差 %', metrics.get('fc_relative_error_pct', '未验收')),
        ('瞬态最大绝对误差 V', metrics.get('transient_max_abs_error_v', '未验收')),
        ('瞬态最大误差 / 脉冲幅值', metrics.get('transient_max_relative_error', '未验收')),
        ('AC / 瞬态样本数', f"{metrics.get('ac_points', '?')} / {metrics.get('tran_points', '?')}"),
        ('瞬态终点 s', metrics.get('tran_end_s', '未验收')),
    ]
    rows = ''.join(f'<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>' for k, v in summary)
    check_rows = ''.join('<tr>'+''.join(f'<td>{esc(c.get(k, ""))}</td>' for k in ['name', 'status', 'actual', 'expected', 'tolerance'])+'</tr>' for c in checks)
    figures = ''.join(f'<figure><img src="data:image/png;base64,{i["data"]}" alt="{esc(i["caption"])}"><figcaption>{esc(i["caption"])} · {esc(i["name"])}<br>SHA-256: {i["sha256"]}</figcaption></figure>' for i in images)
    warning_html = ''.join(f'<li>{esc(x)}</li>' for x in warnings) or '<li>无额外运行警告；已知限制见下。</li>'
    limit_html = ''.join(f'<li>{esc(x)}</li>' for x in limitations)
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(task.get('title', 'RC report'))}</title>
<style>body{{font:15px/1.6 system-ui,sans-serif;max-width:1120px;margin:32px auto;padding:0 24px;color:#172334}}h1,h2{{color:#173854}}table{{border-collapse:collapse;width:100%;margin:16px 0}}th,td{{text-align:left;vertical-align:top;border:1px solid #cbd5df;padding:8px;overflow-wrap:anywhere}}th{{background:#edf2f7}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f7;padding:16px}}img{{max-width:100%;height:auto}}figure{{margin:24px 0}}figcaption{{font-size:12px;color:#526173;overflow-wrap:anywhere}}.status{{font-weight:bold}}@media print{{body{{margin:0}}figure,table{{break-inside:avoid}}}}</style>
<p>AutoCadence · 电路仿真报告</p><h1>{esc(task.get('title', 'RC 低通仿真'))}</h1><p>运行编号：{esc(run_id)}<br>数值验收状态：<span class="status">{esc(status)}</span></p>
<h2>题目与输入</h2><pre>{esc(task.get('question') or '未提供自然语言题目；使用结构化参数。')}</pre><pre>{esc(task_json)}</pre>
<h2>实际结果与判据</h2><p>截止频率相对误差上限 1%；瞬态最大绝对误差除以脉冲幅值上限 0.3%；至少覆盖两个完整脉冲周期。每项实际容差见检查表。</p><table>{rows}</table>
<table><thead><tr><th>检查</th><th>状态</th><th>实际值</th><th>期望值</th><th>容差</th></tr></thead><tbody>{check_rows}</tbody></table>
<h2>本次图像证据</h2>{figures or '<p>没有图像证据。</p>'}<h2>警告与限制</h2><ul>{warning_html}</ul><ul>{limit_html}</ul>
<h2>完整数值记录</h2><pre>{esc(metric_json)}</pre></html>'''
    (root/'report.html').write_text(document, encoding='utf-8')
    fence = chr(96)*3
    md = [f'# {esc(task.get("title", "RC 低通仿真"))}', '', f'运行编号：{esc(run_id)}', f'数值验收状态：{status}', '', '## 题目', '', esc(task.get('question') or '结构化参数输入。'), '', '## 原始参数', '', fence+'json', task_json.replace(fence, '\\u0060\\u0060\\u0060'), fence, '', '## 结果', '']
    md.extend(f'- {k}：{v}' for k, v in summary)
    md.extend(['', '判据：截止频率误差 ≤1%；瞬态最大误差/脉冲幅值 ≤0.3%；至少两个完整周期。', '', '## 检查', ''])
    md.extend(f'- {esc(c.get("name"))}：{esc(c.get("status"))}；实际 {esc(c.get("actual"))}；期望 {esc(c.get("expected"))}；容差 {esc(c.get("tolerance"))}' for c in checks)
    md.extend(['', '## 图像证据', ''])
    for i in images:
        md.extend([f'![{i["caption"]}]({i["name"]})', f'{i["caption"]}；SHA-256 {i["sha256"]}', ''])
    md.extend(['## 警告与限制', ''])
    md.extend(f'- {esc(w)}' for w in warnings+limitations)
    md.extend(['', '## 完整数值', '', fence+'json', metric_json, fence, ''])
    (root/'report.md').write_text('\n'.join(md), encoding='utf-8')
