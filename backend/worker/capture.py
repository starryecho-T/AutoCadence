"""Capture real Cadence windows on a private display (Python 2.6 compatible)."""
from __future__ import print_function

import binascii
import errno
import glob
import json
import os
import re
import signal
import struct
import subprocess
import tempfile
import time

try:
    _string_type = unicode
except NameError:
    _string_type = str


class CaptureError(Exception):
    pass


def _mkdir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def _text(value):
    if isinstance(value, _string_type):
        return value
    return value.decode('latin-1')


def _skill_string(value):
    value = _text(value)
    if any(ord(c) < 32 for c in value):
        raise CaptureError('Control characters are not allowed in SKILL paths')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _stop_group(process):
    """Terminate only a process group created by this module using setsid."""
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError as exc:
        if exc.errno != errno.ESRCH:
            raise
    until = time.time() + 2.0
    while process.poll() is None and time.time() < until:
        time.sleep(.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError as exc:
        if exc.errno != errno.ESRCH:
            raise
    process.wait()


def _command(args, env, deadline):
    output = tempfile.TemporaryFile()
    process = None
    try:
        process = subprocess.Popen(args, env=env, stdout=output,
                                   stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        while process.poll() is None:
            if time.time() >= deadline:
                raise CaptureError('Command timed out: ' + args[0])
            time.sleep(.05)
        output.seek(0)
        return process.returncode, _text(output.read())
    finally:
        if process is not None:
            _stop_group(process)
        output.close()


def _reserve_display():
    """Atomic private locks prevent two workers selecting the same display."""
    token = _text(binascii.hexlify(os.urandom(16)))
    for number in range(180, 240):
        lock = '/tmp/vai-xvfb-%d.lock' % number
        try:
            os.mkdir(lock, int('700', 8))
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                continue
            raise
        if (os.path.exists('/tmp/.X11-unix/X%d' % number) or
                os.path.exists('/tmp/.X%d-lock' % number)):
            os.rmdir(lock)
            continue
        handle = open(os.path.join(lock, 'owner'), 'w')
        try:
            handle.write(token)
        finally:
            handle.close()
        return ':' + str(number), lock, token
    raise CaptureError('No private X display is available')


def _release_display(lock, token):
    if lock is None:
        return
    owner = os.path.join(lock, 'owner')
    try:
        handle = open(owner, 'r')
        try:
            actual = handle.read()
        finally:
            handle.close()
        if actual == token:
            os.unlink(owner)
            os.rmdir(lock)
    except OSError as exc:
        if exc.errno != errno.ENOENT:
            raise


def _windows(tree, stage, run_id, initial):
    matches = []
    for wid, title in re.findall(r'(0x[0-9a-fA-F]+) "([^"]*)"', tree):
        if wid in initial:
            continue
        valid = ((stage == 'schematic' and run_id in title and
                  ('rc_lpf' in title or 'general' in title) and 'schematic' in title.lower()) or
                 (stage == 'waveform' and
                  ('ViVA' in title or 'Visualization' in title)))
        if valid:
            matches.append((wid, title))
    return matches


def _check_xwd(path):
    handle = open(path, 'rb')
    try:
        header = handle.read(100)
    finally:
        handle.close()
    if len(header) != 100:
        raise CaptureError('XWD is empty or has an incomplete header')
    h = struct.unpack('>25I', header)
    if not (h[0] >= 100 and h[1:4] == (7, 2, 24) and h[11] == 32 and
            640 <= h[4] <= 4096 and 400 <= h[5] <= 4096 and
            h[12] >= h[4] * 4 and h[14:17] == (16711680, 65280, 255)):
        raise CaptureError('Unexpected XWD format or window dimensions')
    expected = h[0] + h[19] * 12 + h[12] * h[5]
    if os.path.getsize(path) != expected:
        raise CaptureError('Incomplete XWD pixel data')
    return {'width': h[4], 'height': h[5], 'bytes': expected}


def _script(root, run_id, out):
    # Timers are tenths of a second. Python starts waveform after schematic
    # capture, preventing the waveform window from obscuring the schematic.
    values = {'RUN': _skill_string(run_id),
              'ROOT': _skill_string(os.path.join(root, 'batch', 'psf')),
              'SCH': _skill_string(os.path.join(out, 'schematic_native.png')),
              'READY': _skill_string(os.path.join(out, 'schematic.ready')),
              'WREADY': _skill_string(os.path.join(out, 'waveform.ready')),
              'OUT': _skill_string(out)}
    source = r'''println("VAI_GUI_START")
gwin=deOpenCellView(@RUN@ "rc_lpf" "schematic" "schematic" list(20:20 1520:920) "r")
unless(gwin error("VAI_SCHEMATIC_OPEN_FAILED"))
println(list("VAI_SCHEMATIC_EXPORT" hiExportImage(?window gwin ?fileName @SCH@ ?exportRegion 'entireDesign ?width 1500)))
procedure(vaiSchematicFit()
  hiRaiseWindow(gwin)
  hiZoomAbsoluteScale(gwin 0.9)
  hiRedraw()
  hiRegTimer("vaiSchematicReady()" 30)
)
procedure(vaiSchematicReady()
  f=outfile(@READY@) fprintf(f "ready") close(f)
)
procedure(vaiWave()
  openResults(@ROOT@) selectResults('tran)
  wv=awvCreatePlotWindow(?bBox list(40:40 1540:940))
  unless(wv error("VAI_WAVE_OPEN_FAILED"))
  awvPlotWaveform(wv list(v("vin") v("out")) ?expr list("vin [V]" "out [V]"))
  hiRegTimer("vaiSaveWave()" 50)
)
procedure(vaiSaveWave()
  println(list("VAI_WAVE_EXPORT" awvSaveWindowImage(wv @OUT@ "waveform_native" nil)))
  f=outfile(@WREADY@) fprintf(f "ready") close(f)
  println("VAI_GUI_DONE")
)
hiRegTimer("vaiSchematicFit()" 30)
'''
    for key, value in values.items():
        source = source.replace('@' + key + '@', value)
    config_path = os.path.join(root, 'capture_config.json')
    if os.path.isfile(config_path):
        config = json.load(open(config_path))
        kind = config['analysis']
        source = source.replace('"rc_lpf"', _skill_string(config['cell']))
        select = 'selectResults("dcOp-dc")' if kind == 'op' else 'selectResults("dc-dc")' if kind == 'dc' else "selectResults('%s)" % kind
        source = source.replace("selectResults('tran)", select)
        expressions = config['expressions']
        if kind == 'op':
            helper = '''procedure(gConstant(value)
  let((xx yy)
    xx=drCreateVec('double 2) yy=drCreateVec('double 2)
    drSetElem(xx 0 0.0) drSetElem(xx 1 1.0)
    drSetElem(yy 0 value) drSetElem(yy 1 value)
    drCreateWaveform(xx yy)
  )
)
'''
            source = helper + source
            expressions = ['gConstant(%s)' % e for e in expressions]
        plot = 'awvPlotWaveform(wv list(%s) ?expr list(%s))' % (' '.join(expressions), ' '.join(_skill_string(x) for x in config['labels']))
        source = source.replace('awvPlotWaveform(wv list(v("vin") v("out")) ?expr list("vin [V]" "out [V]"))', plot)
    return source


def capture(root, run_id, env, virt, timeout=100):
    """Return status and write evidence/capture.json, even on capture failure.

    Never attaches to a user display. PNG validation after retrieval is done
    by vai_backend.images.convert_and_validate.
    """
    started = time.time()
    deadline = started + timeout
    root = os.path.abspath(root)
    out = os.path.join(root, 'evidence')
    logs = os.path.join(root, 'logs')
    _mkdir(out)
    _mkdir(logs)
    result = {'ok': False, 'run_id': run_id, 'captured_stages': [], 'windows': {},
              'returncode': None, 'timed_out': False, 'display': None,
              'source_psf': os.path.join(root, 'batch', 'psf')}
    processes = []
    handles = []
    lock = token = auth = None
    auth_created = False
    cadence = None
    try:
        if not re.match(r'^[A-Za-z][A-Za-z0-9_]{0,95}$', run_id):
            raise CaptureError('Invalid run_id')
        if timeout <= 0:
            raise CaptureError('timeout must be positive')
        for name in ('schematic.ready', 'waveform.ready', 'schematic_window.xwd',
                     'waveform_window.xwd', 'schematic_native.png', 'waveform_native.png'):
            if os.path.lexists(os.path.join(out, name)):
                raise CaptureError('Capture evidence already exists; use a fresh run directory')
        display, lock, token = _reserve_display()
        result['display'] = display
        private_env = env.copy()
        private_env['DISPLAY'] = display
        auth = os.path.join(out, '.Xauthority')
        fd = os.open(auth, os.O_WRONLY | os.O_CREAT | os.O_EXCL, int('600', 8))
        os.close(fd)
        auth_created = True
        os.chmod(auth, int('600', 8))
        private_env['XAUTHORITY'] = auth
        cookie = _text(binascii.hexlify(os.urandom(16)))
        rc, text = _command(['xauth', '-f', auth, 'add', display, '.', cookie], private_env, deadline)
        if rc != 0:
            raise CaptureError('xauth failed: ' + text)
        os.chmod(auth, int('600', 8))
        handle = open(os.path.join(logs, 'xvfb.stdout'), 'w')
        handles.append(handle)
        xp = subprocess.Popen(['Xvfb', display, '-screen', '0', '1600x1000x24',
                               '-nolisten', 'tcp', '-auth', auth], env=private_env,
                              stdout=handle, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        processes.append(xp)
        while True:
            if xp.poll() is not None:
                raise CaptureError('Xvfb exited before becoming ready')
            rc, tree = _command(['xwininfo', '-root', '-tree'], private_env, deadline)
            if rc == 0:
                break
            if time.time() >= deadline:
                raise CaptureError('Xvfb readiness timed out')
            time.sleep(.1)
        handle = open(os.path.join(logs, 'wm.stdout'), 'w')
        handles.append(handle)
        wm = subprocess.Popen(['metacity', '--sm-disable'], env=private_env,
                              stdout=handle, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        processes.append(wm)
        time.sleep(.5)
        if wm.poll() is not None:
            raise CaptureError('Private window manager failed')
        rc, before = _command(['xwininfo', '-root', '-tree'], private_env, deadline)
        if rc != 0:
            raise CaptureError('Cannot enumerate private display windows')
        initial = set(re.findall(r'0x[0-9a-fA-F]+', before))
        handle = open(os.path.join(logs, 'windows_before.txt'), 'wb')
        handle.write(before.encode('utf-8'))
        handle.close()
        script_path = os.path.join(logs, 'capture.il')
        handle = open(script_path, 'wb')
        handle.write(_script(root, run_id, out).encode('utf-8'))
        handle.close()
        handle = open(os.path.join(logs, 'capture.stdout'), 'w')
        handles.append(handle)
        cadence = subprocess.Popen([virt, '-64', '-ocean', '-nocdsinit', '-restore',
                                    script_path, '-log', os.path.join(logs, 'capture.log')],
                                   cwd=root, env=private_env, stdin=subprocess.PIPE,
                                   stdout=handle, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        processes.append(cadence)
        for stage in ('schematic', 'waveform'):
            ready = os.path.join(out, stage + '.ready')
            while True:
                if time.time() >= deadline:
                    result['timed_out'] = True
                    raise CaptureError('Timed out waiting for ' + stage + ' capture')
                if cadence.poll() is not None:
                    raise CaptureError('Cadence exited before ' + stage + ' capture')
                if os.path.isfile(ready):
                    rc, tree = _command(['xwininfo', '-root', '-tree'], private_env, deadline)
                    if rc != 0:
                        raise CaptureError('xwininfo failed while locating ' + stage)
                    candidates = _windows(tree, stage, run_id, initial)
                    if len(candidates) > 1:
                        raise CaptureError('Ambiguous ' + stage + ' windows')
                    if candidates:
                        break
                time.sleep(.2)
            handle = open(os.path.join(logs, stage + '_windows.txt'), 'wb')
            handle.write(tree.encode('utf-8'))
            handle.close()
            wid, title = candidates[0]
            dest = os.path.join(out, stage + '_window.xwd')
            rc, output = _command(['xwd', '-silent', '-screen', '-frame', '-id', wid,
                                   '-out', dest], private_env, deadline)
            if rc != 0:
                raise CaptureError('xwd failed for ' + stage + ': ' + output)
            details = _check_xwd(dest)
            details.update({'run_id': run_id, 'window_id': wid, 'title': title,
                            'xwd': os.path.basename(dest), 'returncode': rc,
                            'source_psf': result['source_psf'] if stage == 'waveform' else None})
            result['windows'][stage] = details
            result['captured_stages'].append(stage)
            if stage == 'schematic':
                cadence.stdin.write(b'vaiWave()\n')
                cadence.stdin.flush()
        cadence.stdin.write(b'exit()\n')
        cadence.stdin.flush()
        result['exit_requested'] = True
        exit_deadline = min(deadline, time.time() + 10)
        while cadence.poll() is None and time.time() < exit_deadline:
            time.sleep(.1)
        if cadence.poll() is None:
            result['timed_out'] = True
            raise CaptureError('Cadence did not exit after capture')
        result['returncode'] = cadence.returncode
        if cadence.returncode != 0:
            raise CaptureError('Cadence exited with code ' + str(cadence.returncode))
        canonical_native = os.path.join(out, 'waveform_native.png')
        if not os.path.isfile(canonical_native):
            native = glob.glob(os.path.join(out, 'waveform_nativewindow*.png'))
            if len(native) != 1 or os.path.getsize(native[0]) == 0:
                raise CaptureError('Expected one nonempty native ViVA image')
            os.rename(native[0], canonical_native)
        for name in ('schematic_native.png', 'waveform_native.png'):
            path = os.path.join(out, name)
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                raise CaptureError('Native image is missing or empty: ' + name)
        result['ok'] = True
    except Exception as exc:
        result['error'] = _text(str(exc))
        if time.time() >= deadline:
            result['timed_out'] = True
    finally:
        cleanup_errors = []
        for process in reversed(processes):
            try:
                _stop_group(process)
            except Exception as exc:
                cleanup_errors.append(str(exc))
        for handle in handles:
            handle.close()
        if cadence is not None:
            result['returncode'] = cadence.returncode
            if cadence.stdin is not None:
                try:
                    cadence.stdin.close()
                except IOError:
                    pass
        if auth_created:
            try:
                os.unlink(auth)
            except OSError as exc:
                if exc.errno != errno.ENOENT:
                    cleanup_errors.append(str(exc))
        try:
            _release_display(lock, token)
        except Exception as exc:
            cleanup_errors.append(str(exc))
        if cleanup_errors:
            result['cleanup_errors'] = cleanup_errors
            result['ok'] = False
        result['elapsed_s'] = time.time() - started
        handle = open(os.path.join(out, 'capture.json'), 'w')
        try:
            json.dump(result, handle, indent=2, sort_keys=True)
        finally:
            handle.close()
    return result
