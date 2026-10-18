# -*- coding: utf-8 -*-
"""M4 end-to-end demo: question -> derived params -> confirmation -> real run -> evidence answer.

Plays the role of the in-app agent (the part that uses the user's own API in
the product): reads a behaviour-specified question, derives a legal TaskSpec
via the skill design rules, "confirms" it (recorded in the summary), submits
it through the public API, and composes the final answer strictly from the
metrics/artifacts of that single run.

Set VAI_BASE (e.g. http://127.0.0.1:8765) to drive an already-running backend
(the frontend demo setup); otherwise a uvicorn server is booted in-thread.

Exit 0 == M4 demo PASS. Summary -> docs/m4_demo_summary.json.
"""
from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        pass
sys.path.insert(0, str(ROOT))

from skill import VaiClient, derive_rc_from_cutoff, precheck_spec  # noqa: E402

QUESTION = ('用一阶 RC 低通滤波器设计一个音频抗混叠前置滤波器，要求截止频率约为 1 kHz。'
            '使用 0 到 2 V、周期 4 ms、脉宽 2 ms 的脉冲激励验证其时域响应，'
            '并给出 -3 dB 截止频率与脉冲响应波形。')
TARGET_FC_HZ = 1000.0
PULSE = {'low_v': 0, 'high_v': 2, 'period_s': 0.004, 'width_s': 0.002,
         'rise_s': 1e-9, 'fall_s': 1e-9, 'delay_s': 1e-6}
TRANSIENT_STOP_S = 0.0083   # >= delay + 2.05*period = 8.201 ms (two full cycles)
MAX_STEP_S = 2e-6           # <= min(tau/20 = 8 us, period/200 = 20 us, width/20 = 100 us)
SUMMARY_PATH = ROOT / 'docs' / 'm4_demo_summary.json'


def log(message: str) -> None:
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {message}', flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def main() -> int:
    started = time.monotonic()
    log('M4 demo: question -> confirmed params -> real run -> evidence answer')

    # ---- step 0: backend ----------------------------------------------------
    base = os.getenv('VAI_BASE', '').strip()
    server = None
    if base:
        client = VaiClient(base)
        log(f'using external backend at {base}')
    else:
        import uvicorn
        from vai_backend.api import create_app
        from vai_backend.config import Settings
        base = 'http://127.0.0.1:8765'
        settings = Settings(data_dir=ROOT / 'runs', host='127.0.0.1', port=8765)
        server = uvicorn.Server(uvicorn.Config(create_app(settings), host='127.0.0.1',
                                               port=8765, log_level='warning', access_log=False))
        threading.Thread(target=server.run, name='vai-uvicorn', daemon=True).start()
        client = VaiClient(base)
        for _ in range(60):
            try:
                if client.health()['status'] == 'ok':
                    break
            except Exception:
                pass
            time.sleep(0.5)
    assert client.health()['status'] == 'ok'
    log('backend healthy')

    problems: list[str] = []
    try:
        # ---- step 1: classify question (bounded parse; agent reads result) ----
        parsed = client.parse(QUESTION)
        log(f'parse: supported={parsed["supported"]} missing={parsed["missing_fields"]} '
            f'warnings={len(parsed["warnings"])}')
        if parsed['missing_fields'] != ['r_ohm', 'c_f']:
            problems.append(f'unexpected missing_fields: {parsed["missing_fields"]}')
        # parse early-returns while R/C are absent, so warnings stay empty here:
        # extracting the stimulus conditions from the question text is the
        # agent's job (exactly the role the product gives the user's own API).
        log('parse early-returned with missing R/C (behaviour question); '
            'agent reads stimulus conditions from the question text')

        # ---- step 2: derive standard values from the behavioural target ------
        derived = derive_rc_from_cutoff(TARGET_FC_HZ)
        log(f'derived R={derived["r_ohm"]:g} Ohm, C={derived["c_f"]:g} F -> '
            f'fc={derived["fc_achievable_hz"]:.2f} Hz (err {derived["error"] * 100:.2f}%)')

        # ---- step 3: assemble candidate spec (question overrides defaults) ---
        spec = {
            'schema_version': '1.0', 'template_id': 'rc_lowpass',
            'title': 'M4 demo: 1 kHz RC anti-alias low-pass',
            'question': QUESTION,
            'r_ohm': derived['r_ohm'], 'c_f': derived['c_f'],
            'pulse': PULSE,
            'ac': {'start_hz': 10, 'stop_hz': 1e6, 'points_per_decade': 50},
            'transient': {'stop_s': TRANSIENT_STOP_S, 'max_step_s': MAX_STEP_S},
        }
        local_problems = precheck_spec(spec)
        log(f'precheck: {len(local_problems)} problem(s)')
        if local_problems:
            problems.extend(f'precheck: {p}' for p in local_problems)

        # ---- step 4: user confirmation (demo records the confirmation) -------
        confirmation = {
            'confirmed_at': utc_now(),
            'mode': 'demo_auto',
            'shown_to_user': {
                'r_ohm': spec['r_ohm'], 'c_f': spec['c_f'],
                'fc_requested_hz': TARGET_FC_HZ,
                'fc_achievable_hz': derived['fc_achievable_hz'],
                'standard_value_error_pct': derived['error'] * 100,
                'pulse': PULSE, 'transient': spec['transient'], 'ac': spec['ac'],
                'parse_warnings': parsed['warnings'],
                'parse_defaults_applied': parsed['defaults_applied'],
            },
        }
        log('parameters confirmed (demo auto-confirm; product requires real user action)')

        # ---- step 5: submit and poll -----------------------------------------
        run = client.submit(spec)
        log(f'submitted -> {run["run_id"]} ({run["status"]})')
        run = client.wait_run(run['run_id'], timeout=360, poll=1.5,
                              on_stage=lambda s: log(f'  stage {s["name"]}: {s["status"]}')
                              if s['status'] == 'succeeded' else None)
        if run['status'] != 'succeeded':
            problems.append(f'run failed: {run.get("error")}')
        metrics = run.get('metrics') or {}
        fc_theory = 1 / (2 * math.pi * spec['r_ohm'] * spec['c_f'])
        fc = metrics.get('fc_hz')
        log(f'run {run["run_id"]}: {run["status"]}; fc={fc} Hz '
            f'(spec theory {fc_theory:.2f} Hz; requested 1000 Hz)')
        if run['status'] == 'succeeded':
            if metrics.get('validation_status') != 'PASS':
                problems.append('metrics validation_status is not PASS')
            if not isinstance(fc, (int, float)) or abs(fc / fc_theory - 1) > 0.01:
                problems.append(f'fc {fc} outside 1% of spec theory {fc_theory}')
            edges = next((c['actual'] for c in metrics.get('checks', [])
                          if c['name'] == 'pulse_edges'), {})
            if min(edges.get('rising', [0])) < 2 or min(edges.get('falling', [0])) < 2:
                problems.append(f'incomplete pulse cycles: {edges}')

        # ---- step 6: evidence answer from THIS run ---------------------------
        report_md = metrics_json = wave_png = None
        if run['status'] == 'succeeded':
            report_md = client.artifact_bytes_by_filename(run, 'report.md').decode('utf-8')
            metrics_json = json.loads(client.artifact_bytes_by_filename(run, 'metrics.json'))
            wave_png = client.artifact_by_filename(run, 'waveform_window.png')
        answer = None
        if run['status'] == 'succeeded' and metrics_json:
            err_pct = metrics_json['fc_relative_error_pct']
            answer = (
                f'采用 R={spec["r_ohm"]:g} Ω、C={spec["c_f"] * 1e9:g} nF 的一阶 RC 低通'
                f'（标准值舍入后 fc={metrics_json["fc_hz"]:.1f} Hz，与 1 kHz 目标偏差 '
                f'{abs(metrics_json["fc_hz"] / TARGET_FC_HZ - 1) * 100:.2f}%）。'
                f'本次 Spectre 实测 -3 dB 截止频率 {metrics_json["fc_hz"]:.3f} Hz'
                f'（对元件理论值误差 {err_pct:.4f}%），时间常数 τ={metrics_json["tau_s"] * 1e6:g} µs，'
                f'τ 时刻输出 {metrics_json["vout_at_tau"]:.4f} V。'
                f'0→2 V、周期 4 ms 脉冲激励下瞬态覆盖 {metrics_json["tran_points"]} 点'
                f'（≥2 个完整周期，升沿×{min(edges["rising"])}、降沿×{min(edges["falling"])}），'
                f'RC 递推对比最大相对误差 {metrics_json["transient_max_relative_error"]:.2e}。'
                f'原理图与波形截图、完整数值报告（report.html / report.md）均来自本次运行 '
                f'{run["run_id"]}，未使用任何合成数据。')
            print('\n' + '=' * 78, flush=True)
            print('ANSWER (composed strictly from run ' + run['run_id'] + ' evidence):', flush=True)
            print(answer, flush=True)
            print('=' * 78 + '\n', flush=True)

        summary = {
            'milestone': 'M4', 'verdict': 'PASS' if not problems else 'FAIL',
            'question': QUESTION, 'started_at': confirmation['confirmed_at'],
            'finished_at': utc_now(), 'total_elapsed_s': round(time.monotonic() - started, 1),
            'parse': {'supported': parsed['supported'],
                      'missing_fields': parsed['missing_fields'],
                      'warnings': parsed['warnings'],
                      'defaults_applied': parsed['defaults_applied']},
            'derivation': derived, 'precheck_problems': local_problems,
            'confirmation': confirmation, 'submitted_spec': spec,
            'run': {'run_id': run['run_id'], 'status': run['status'],
                    'error': run.get('error'),
                    'metrics': {k: metrics.get(k) for k in
                                ('fc_hz', 'fc_theory_hz', 'fc_relative_error_pct', 'vout_at_tau',
                                 'tran_points', 'ac_points', 'transient_max_relative_error')},
                    'report_md_head': report_md[:400] if report_md else None,
                    'waveform_png': {'bytes': wave_png['bytes'], 'sha256': wave_png['sha256']}
                    if wave_png else None},
            'answer': answer, 'problems': problems,
        }
        SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                encoding='utf-8')
        for problem in problems:
            print(f'FAILURE: {problem}', file=sys.stderr, flush=True)
        log(f'verdict: {summary["verdict"]}; summary -> {SUMMARY_PATH}')
        return 0 if not problems else 1
    finally:
        if server is not None:
            server.should_exit = True


if __name__ == '__main__':
    sys.exit(main())
