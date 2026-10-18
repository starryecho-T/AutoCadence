"""Deterministic acceptance of exported Spectre data, without fallback values."""
from __future__ import annotations
import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from .models import TaskSpec


class AnalysisError(Exception):
    def __init__(self, code: str, message: str, stage: str = 'validation'):
        super().__init__(message)
        self.code, self.stage, self.message = code, stage, message


def _fail(code, message):
    raise AnalysisError(code, message)


def _read_wave(path: Path, positive_x=False):
    if not path.is_file():
        _fail('MISSING_WAVEFORM', f'Missing required waveform: {path.name}')
    rows, quantization = [], []
    for line_no, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
        s = line.strip()
        if not s or s.startswith(('#', ';', '//')):
            continue
        fields = s.split()
        if not re.match(r'^[+\-\.\d]|^(?:nan|inf)', fields[0], re.I):
            continue
        if len(fields) != 2:
            _fail('MALFORMED_WAVEFORM', f'{path.name}:{line_no}: expected two numeric columns')
        try:
            x, y = (float(v) for v in fields)
        except (ValueError, OverflowError):
            _fail('MALFORMED_WAVEFORM', f'{path.name}:{line_no}: invalid numeric data')
        if not (math.isfinite(x) and math.isfinite(y)):
            _fail('NONFINITE_WAVEFORM', f'{path.name}:{line_no}: non-finite value')
        try:
            q = .5 * 10.0 ** Decimal(fields[0]).as_tuple().exponent
        except (InvalidOperation, OverflowError):
            _fail('MALFORMED_WAVEFORM', f'{path.name}:{line_no}: invalid axis precision')
        if x < 0 or (positive_x and x == 0):
            _fail('INVALID_WAVEFORM_AXIS', f'{path.name}:{line_no}: invalid axis value {x}')
        if rows and x <= rows[-1][0]:
            _fail('NONMONOTONIC_WAVEFORM', f'{path.name}:{line_no}: axis must strictly increase; export at higher precision')
        rows.append((x, y))
        quantization.append(q)
    if len(rows) < 3:
        _fail('INSUFFICIENT_WAVEFORM', f'{path.name}: fewer than three data points')
    return rows, quantization


def _aligned(a, b, label):
    if len(a) != len(b) or any(x[0] != y[0] for x, y in zip(a, b)):
        _fail('MISALIGNED_WAVEFORMS', f'{label} input/output axes must match exactly')


def _interp(rows, x):
    if x < rows[0][0] or x > rows[-1][0]:
        return None
    for (x0, y0), (x1, y1) in zip(rows, rows[1:]):
        if x0 <= x <= x1:
            return y0 + (y1-y0) * ((x-x0)/(x1-x0))
    return rows[-1][1]


def rc_response(times, inputs, tau, initial_v=None):
    """Exact RC recurrence for each piecewise-linear measured input segment."""
    if tau <= 0 or len(times) != len(inputs) or not times:
        raise ValueError('positive tau and aligned nonempty arrays required')
    out = [inputs[0] if initial_v is None else initial_v]
    for t0, t1, u0, u1 in zip(times, times[1:], inputs, inputs[1:]):
        h = t1-t0
        if h <= 0:
            raise ValueError('times must strictly increase')
        z = h/tau
        one_minus_e = -math.expm1(-z)
        ramp_factor = (z/2-z*z/6+z**3/24-z**4/120) if z < 1e-4 else 1-one_minus_e/z
        out.append(out[-1] + (u0-out[-1])*one_minus_e + (u1-u0)*ramp_factor)
    return out


def _crossings(rows, level, rising):
    result = []
    for (t0, y0), (t1, y1) in zip(rows, rows[1:]):
        crosses = y0 < level <= y1 if rising else y0 > level >= y1
        if crosses:
            result.append(t0 + (level-y0)*(t1-t0)/(y1-y0))
    return result


def analyze(task: dict, evidence_dir: Path) -> dict:
    try:
        spec = TaskSpec.model_validate(task).model_dump()
    except Exception as exc:
        _fail('INVALID_TASK', f'Task validation failed: {exc}')
    evidence_dir = Path(evidence_dir)
    ac_out, _ = _read_wave(evidence_dir/'ac_vdb_out.txt', True)
    ac_in, _ = _read_wave(evidence_dir/'ac_vdb_in.txt', True)
    tran_out, tq = _read_wave(evidence_dir/'tran_out.txt')
    tran_in, iq = _read_wave(evidence_dir/'tran_in.txt')
    _aligned(ac_out, ac_in, 'AC')
    _aligned(tran_out, tran_in, 'Transient')
    checks = []

    def check(name, ok, actual, expected, tolerance=None, code=None):
        if not ok:
            _fail(code or name.upper(), f'{name}: measured={actual!r}; expected={expected!r}; tolerance={tolerance!r}')
        checks.append({'name': name, 'status': 'PASS', 'actual': actual, 'expected': expected, 'tolerance': tolerance})

    check('waveform_axes', True, {'ac_points': len(ac_out), 'tran_points': len(tran_out)}, 'finite, aligned, strictly increasing')
    tau = spec['r_ohm']*spec['c_f']
    fc_theory = 1/(2*math.pi*tau)
    ac_spec, tr_spec, p = spec['ac'], spec['transient'], spec['pulse']
    check('ac_range', math.isclose(ac_out[0][0], ac_spec['start_hz'], rel_tol=1e-6) and math.isclose(ac_out[-1][0], ac_spec['stop_hz'], rel_tol=1e-6), [ac_out[0][0], ac_out[-1][0]], [ac_spec['start_hz'], ac_spec['stop_hz']], 1e-6)
    gain = [(o[0], o[1]-i[1]) for o, i in zip(ac_out, ac_in)]
    cutoff_db = -10*math.log10(2)
    brackets = [(a, b) for a, b in zip(gain, gain[1:]) if a[1] > cutoff_db >= b[1]]
    check('ac_cutoff_crossing', len(brackets) == 1, len(brackets), 1, code='AC_CUTOFF_NOT_UNIQUE')
    a, b = brackets[0]
    fraction = (cutoff_db-a[1])/(b[1]-a[1])
    fc = math.exp(math.log(a[0])+fraction*(math.log(b[0])-math.log(a[0])))
    fc_error = abs(fc/fc_theory-1)
    check('cutoff_frequency', fc_error <= .01, fc, fc_theory, {'relative': .01}, 'AC_CUTOFF_MISMATCH')
    max_gain_error_db = max(abs(db + 10*math.log10(1+(f/fc_theory)**2)) for f, db in gain)
    check('ac_transfer_shape', max_gain_error_db <= .05, max_gain_error_db, 0, {'absolute_db': .05}, 'AC_TRANSFER_MISMATCH')
    time_precision = max(tq+iq)
    time_tol = max(4*time_precision, tr_spec['max_step_s']*.02, 1e-12)
    check('transient_start', abs(tran_in[0][0]) <= max(4*iq[0], 1e-15), tran_in[0][0], 0, 1e-15, 'TRANSIENT_START_MISMATCH')
    needed_end = p['delay_s']+2*p['period_s']
    check('complete_pulse_cycles', tran_in[-1][0]+time_tol >= needed_end, tran_in[-1][0], f'>={needed_end} s (two complete periods)', time_tol, 'INSUFFICIENT_PULSE_COVERAGE')
    check('transient_stop', abs(tran_in[-1][0]-tr_spec['stop_s']) <= time_tol, tran_in[-1][0], tr_spec['stop_s'], time_tol, 'TRANSIENT_STOP_MISMATCH')
    max_step = max(b[0]-a[0] for a, b in zip(tran_in, tran_in[1:]))
    check('transient_max_step', max_step <= tr_spec['max_step_s']*1.02+4*time_precision, max_step, tr_spec['max_step_s'], .02, 'TRANSIENT_STEP_TOO_LARGE')
    amplitude = p['high_v']-p['low_v']
    low, high = min(v for _, v in tran_in), max(v for _, v in tran_in)
    amp_tol = max(amplitude*.002, 1e-9)
    check('pulse_amplitude', abs(low-p['low_v']) <= amp_tol and abs(high-p['high_v']) <= amp_tol, [low, high], [p['low_v'], p['high_v']], amp_tol, 'PULSE_AMPLITUDE_MISMATCH')
    up = [_crossings(tran_in, p['low_v']+amplitude*x, True) for x in (.1, .5, .9)]
    down = [_crossings(tran_in, p['low_v']+amplitude*x, False) for x in (.1, .5, .9)]
    check('pulse_edges', min(map(len, up)) >= 2 and min(map(len, down)) >= 2 and len({len(x) for x in up}) == 1 and len({len(x) for x in down}) == 1, {'rising': list(map(len, up)), 'falling': list(map(len, down))}, 'at least two complete rising and falling edges', code='INSUFFICIENT_PULSE_EDGES')
    rises = [(b-a)/.8 for a, b in zip(up[0], up[2])]
    falls = [(a-b)/.8 for a, b in zip(down[0], down[2])]
    rise_tol = max(p['rise_s']*.25, 4*time_precision, 1e-12)
    fall_tol = max(p['fall_s']*.25, 4*time_precision, 1e-12)
    check('pulse_rise', all(abs(x-p['rise_s']) <= rise_tol for x in rises), rises, p['rise_s'], rise_tol, 'PULSE_RISE_MISMATCH')
    check('pulse_fall', all(abs(x-p['fall_s']) <= fall_tol for x in falls), falls, p['fall_s'], fall_tol, 'PULSE_FALL_MISMATCH')
    periods = [b-a for a, b in zip(up[1], up[1][1:])]
    period_tol = max(p['period_s']*1e-4, time_tol)
    check('pulse_period', bool(periods) and all(abs(x-p['period_s']) <= period_tol for x in periods), periods, p['period_s'], period_tol, 'PULSE_PERIOD_MISMATCH')
    widths = []
    for n, falling_mid in enumerate(down[1]):
        if n >= len(up[1]):
            break
        widths.append(falling_mid-up[1][n]-(rises[n]+falls[n])/2)
    width_tol = max(p['width_s']*1e-4, time_tol)
    check('pulse_width', len(widths) >= 2 and all(abs(x-p['width_s']) <= width_tol for x in widths), widths, p['width_s'], width_tol, 'PULSE_WIDTH_MISMATCH')
    measured_delay = up[1][0]-rises[0]/2
    delay_tol = max(time_tol, p['delay_s']*1e-4, rise_tol)
    check('pulse_delay', abs(measured_delay-p['delay_s']) <= delay_tol, measured_delay, p['delay_s'], delay_tol, 'PULSE_DELAY_MISMATCH')
    check('pulse_phase', all(abs(mid-(p['delay_s']+n*p['period_s']+p['rise_s']/2)) <= max(delay_tol, period_tol) for n, mid in enumerate(up[1])), up[1], 'delay + n*period + rise/2', max(delay_tol, period_tol), 'PULSE_PHASE_MISMATCH')
    predicted = rc_response([t for t, _ in tran_in], [v for _, v in tran_in], tau, p['low_v'])
    errors = [abs(y-pred) for (_, y), pred in zip(tran_out, predicted)]
    max_response_error = max(errors)
    check('transient_rc_response', max_response_error/amplitude <= .003, max_response_error/amplitude, 0, {'relative_to_pulse_amplitude': .003}, 'TRANSIENT_RESPONSE_MISMATCH')
    return {
        'validation_status': 'PASS', 'checks': checks,
        'ac_points': len(ac_out), 'tran_points': len(tran_out),
        'ac_input_output_aligned': True, 'tran_input_output_aligned': True,
        'tau_s': tau, 'fc_hz': fc, 'fc_theory_hz': fc_theory,
        'fc_relative_error': fc_error, 'fc_relative_error_pct': fc_error*100,
        'max_ac_gain_error_db': max_gain_error_db,
        'vout_at_100us': _interp(tran_out, 1e-4), 'vout_at_tau': _interp(tran_out, tau),
        'tran_end_s': tran_out[-1][0], 'vout_at_end': tran_out[-1][1],
        'transient_max_abs_error_v': max_response_error,
        'transient_max_relative_error': max_response_error/amplitude,
        'transient_reference': 'Exact RC recurrence for piecewise-linear measured vin; initial output equals specified low_v.',
        'pulse_measured': {'low_v': low, 'high_v': high, 'rise_s': rises, 'fall_s': falls, 'period_s': periods, 'width_s': widths, 'delay_s': measured_delay},
        'tolerances': {'fc_relative': .01, 'response_relative_to_amplitude': .003, 'rise_s': rise_tol, 'fall_s': fall_tol, 'time_quantization_s': time_precision},
        'waveform_source': 'Spectre numeric data exported from this run; no synthetic values or LLM estimates.',
        'limitations': ['Only the supported ideal RC low-pass topology is assessed.', 'Rise/fall use 10–90% crossings divided by 0.8 and exported time precision.'],
    }
