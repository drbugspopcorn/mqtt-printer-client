'''
    systemd entry point.  Checks whether the last code update is failing to start, rolls back if so,
    then hands over to printer_client.py.

    Keep this file stdlib-only and boring.  It's what recovers a box from a bad update, so if this
    breaks, rollback breaks with it.

    How rollback works:
        updater.update() resets to the new commit and writes STATE_FILE {prev, new, attempts: 0}
        every launch bumps attempts
        printer_client deletes STATE_FILE once it has connected and been up for a minute
        if attempts passes MAX_ATTEMPTS first, we reset back to prev and record LAST_ROLLBACK_FILE
'''
import json
import os
import subprocess
import sys
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(APP_DIR, '.update_state.json')
LAST_ROLLBACK_FILE = os.path.join(APP_DIR, '.last_rollback.json')
REQUIREMENTS_FILE = os.path.join(APP_DIR, 'requirements.common.txt')
MAX_ATTEMPTS = 3


def log(msg):
    print(f"launcher: {msg}", flush=True)


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def git(*args, timeout=120):
    return subprocess.run(['git', '-C', APP_DIR] + list(args), capture_output=True, text=True,
                          timeout=timeout, check=True).stdout.strip()


def pip_install():
    cmd = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', REQUIREMENTS_FILE]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0 and 'externally-managed' in result.stderr:
        # system python on newer Pi OS / Ubuntu without a venv (old installs)
        result = subprocess.run(cmd + ['--break-system-packages'], capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(f"pip install failed: {result.stderr[-1500:]}")


def rollback(state, reason):
    log(f"rolling back {state.get('new')} -> {state.get('prev')}: {reason}")
    git('reset', '--hard', state['prev'])
    changed = git('diff', '--name-only', state['prev'], state['new']).splitlines()
    if any('requirements' in f for f in changed):
        pip_install()
    write_json(LAST_ROLLBACK_FILE, {
        'from': state.get('new'),
        'to': state.get('prev'),
        'reason': reason,
        'ts': time.time(),
    })
    os.remove(STATE_FILE)


def check_pending_update():
    state = read_json(STATE_FILE)
    if not state:
        return
    state['attempts'] = state.get('attempts', 0) + 1
    if state['attempts'] > MAX_ATTEMPTS:
        rollback(state, f"failed to come up healthy after {MAX_ATTEMPTS} starts")
    else:
        log(f"update to {state.get('new')} pending health check (start {state['attempts']}/{MAX_ATTEMPTS})")
        write_json(STATE_FILE, state)


if __name__ == '__main__':
    try:
        check_pending_update()
    except Exception as e:
        log(f"update check failed, starting anyway: {e}")
    os.chdir(APP_DIR)
    os.execv(sys.executable, [sys.executable, '-u', os.path.join(APP_DIR, 'printer_client.py')])
