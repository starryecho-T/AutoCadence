"""Stdlib-only client and design helpers for the VAI backend (API v1.0).

No third-party dependencies: any Python 3.9+ environment (or agent sandbox)
can drive the backend with this module. The server remains authoritative for
validation (HTTP 422); precheck_spec() is only a fast advisory mirror.
"""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request

DEFAULT_BASE = 'http://127.0.0.1:8765'

# E24 resistor decades and common capacitor values used by derive_rc_from_cutoff.
_E24_BASE = (1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
             3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1)
_R_DECADES = (1.0, 1e1, 1e2, 1e3, 1e4, 1e5)
_C_BASE = (1e-12, 2.2e-12, 3.3e-12, 4.7e-12, 6.8e-12,
           1e-11, 2.2e-11, 3.3e-11, 4.7e-11, 6.8e-11,
           1e-10, 2.2e-10, 3.3e-10, 4.7e-10, 6.8e-10,
           1e-9, 2.2e-9, 3.3e-9, 4.7e-9, 6.8e-9,
           1e-8, 2.2e-8, 3.3e-8, 4.7e-8, 6.8e-8,
           1e-7, 1.5e-7, 2.2e-7, 3.3e-7, 4.7e-7, 6.8e-7,
           1e-6, 1.5e-6, 2.2e-6, 3.3e-6, 4.7e-6, 6.8e-6,
           1e-5, 2.2e-5, 4.7e-5, 1e-4, 2.2e-4, 4.7e-4)


class VaiError(RuntimeError):
    """HTTP-level failure; carries status and the backend error.code."""

    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(f'{code} (HTTP {status}): {message}')
        self.status, self.code, self.details = status, code, details


class VaiClient:
    def __init__(self, base_url: str = DEFAULT_BASE, token: str | None = None,
                 timeout: float = 30.0):
        self.base = base_url.rstrip('/')
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict | None = None,
                 timeout: float | None = None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            request.add_header('Content-Type', 'application/json')
        if self.token:
            request.add_header('Authorization', 'Bearer ' + self.token)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode('utf-8', 'replace')
            try:
                error = json.loads(payload).get('error', {})
            except ValueError:
                error = {}
            raise VaiError(exc.code, error.get('code', 'HTTP_ERROR'),
                           error.get('message', payload[:500]),
                           error.get('details')) from exc

    # ---- API v1.0 endpoints -------------------------------------------------
    def health(self) -> dict:
        return self._request('GET', '/health')

    def capabilities(self) -> dict:
        return self._request('GET', '/api/v1/capabilities')

    def parse(self, text: str) -> dict:
        return self._request('POST', '/api/v1/parse', {'text': text})

    def submit(self, spec: dict) -> dict:
        return self._request('POST', '/api/v1/runs', spec)

    def get_run(self, run_id: str) -> dict:
        return self._request('GET', f'/api/v1/runs/{run_id}')

    def list_runs(self, limit: int = 50) -> list[dict]:
        return self._request('GET', f'/api/v1/runs?limit={limit}')['runs']

    def wait_run(self, run_id: str, timeout: float = 360.0,
                 poll: float = 1.5, on_stage=None) -> dict:
        deadline = time.monotonic() + timeout
        seen: set[str] = set()
        while True:
            run = self.get_run(run_id)
            if on_stage:
                for stage in run.get('stages', []):
                    key = stage['name'] + ':' + stage['status']
                    if key not in seen:
                        seen.add(key)
                        on_stage(stage)
            if run['status'] in ('succeeded', 'failed'):
                return run
            if time.monotonic() > deadline:
                raise TimeoutError(f'{run_id}: no terminal state within {timeout} s')
            time.sleep(poll)

    def artifact_bytes(self, run_id: str, artifact_id: str,
                       timeout: float = 120.0) -> bytes:
        request = urllib.request.Request(
            f'{self.base}/api/v1/runs/{run_id}/artifacts/{artifact_id}')
        if self.token:
            request.add_header('Authorization', 'Bearer ' + self.token)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()

    def artifact_by_filename(self, run: dict, filename: str):
        return next((a for a in run.get('artifacts', [])
                     if a.get('filename') == filename), None)

    def artifact_bytes_by_filename(self, run: dict, filename: str) -> bytes:
        meta = self.artifact_by_filename(run, filename)
        if meta is None:
            raise KeyError(f'artifact not found: {filename}')
        return self.artifact_bytes(run['run_id'], meta['id'])


# ---- design helpers ---------------------------------------------------------

def derive_rc_from_cutoff(fc_hz: float, max_error: float = 0.02) -> dict:
    """Pick an E24 resistor x common capacitor pair whose cutoff is closest
    to the requested frequency (within max_error). Ties are broken toward a
    resistor near 10 kOhm on a log scale, which keeps impedances in the
    practical range. Returns r_ohm, c_f, fc_achievable_hz and the relative
    error of the standard-value rounding."""
    if not fc_hz > 0:
        raise ValueError('fc_hz must be positive')
    best, best_key = None, None
    for r_base in _E24_BASE:
        for r_mult in _R_DECADES:
            r = r_base * r_mult
            if not 10 <= r <= 1e6:
                continue
            for c in _C_BASE:
                if not 1e-12 <= c <= 1e-3:
                    continue
                fc = 1 / (2 * math.pi * r * c)
                err = abs(fc / fc_hz - 1)
                key = (err, abs(math.log10(r) - 4.0))
                if best_key is None or key < best_key:
                    best = {'r_ohm': r, 'c_f': c, 'fc_achievable_hz': fc, 'error': err}
                    best_key = key
    if best is None or best['error'] > max_error:
        raise ValueError(
            f'no standard RC pair within {max_error:.1%} of {fc_hz} Hz '
            f'(best {best["fc_achievable_hz"]:.4g} Hz, err {best["error"]:.2%})')
    return best


def precheck_spec(spec: dict) -> list[str]:
    """Advisory mirror of the TaskSpec constraints (models.py). Empty list
    means the spec is expected to be accepted; the server 422 is final."""
    problems: list[str] = []
    r, c = spec.get('r_ohm'), spec.get('c_f')
    if not isinstance(r, (int, float)) or not 10 <= r <= 1e6:
        problems.append('r_ohm must be within [10, 1e6]')
    if not isinstance(c, (int, float)) or not 1e-12 <= c <= 1e-3:
        problems.append('c_f must be within [1e-12, 1e-3]')
    if problems:
        return problems
    tau = r * c
    fc = 1 / (2 * math.pi * tau)
    pulse, ac, tran = spec.get('pulse', {}), spec.get('ac', {}), spec.get('transient', {})
    period, width = pulse.get('period_s', .002), pulse.get('width_s', .001)
    rise, fall = pulse.get('rise_s', 1e-9), pulse.get('fall_s', 1e-9)
    delay = pulse.get('delay_s', 1e-6)
    if pulse.get('high_v', 1) <= pulse.get('low_v', 0):
        problems.append('high_v must exceed low_v')
    if rise + width + fall >= period:
        problems.append('rise + width + fall must be less than period')
    if not ac.get('start_hz', 10) <= fc / 5:
        problems.append(f'AC start must be <= fc/5 = {fc / 5:.6g} Hz')
    if not ac.get('stop_hz', 1e6) >= fc * 5:
        problems.append(f'AC stop must be >= fc*5 = {fc * 5:.6g} Hz')
    if math.log10(ac.get('stop_hz', 1e6) / ac.get('start_hz', 10)) \
            * ac.get('points_per_decade', 50) > 1500:
        problems.append('AC point budget exceeded (>1500)')
    stop, step = tran.get('stop_s', .004201), tran.get('max_step_s', 1e-6)
    if stop < delay + 2.05 * period:
        problems.append(f'transient stop must be >= delay + 2.05*period = {delay + 2.05 * period:.6g} s')
    if step > min(tau / 20, period / 200, width / 20):
        problems.append(f'max_step_s must be <= min(tau/20, period/200, width/20) = '
                        f'{min(tau / 20, period / 200, width / 20):.6g} s')
    if stop / step > 60000:
        problems.append('transient point budget exceeded (>60000)')
    return problems
