'''
    Self-update from GitHub.  The actual restart is left to the caller (exit and let systemd bring us back);
    launcher.py takes care of rolling back if the new code won't come up.
'''
import logging
import os
import subprocess
import time

from launcher import LAST_ROLLBACK_FILE, STATE_FILE, git, pip_install, read_json, write_json

logger = logging.getLogger(__name__)

HEALTHY_AFTER_SECONDS = 60


def is_git_checkout():
    try:
        git('rev-parse', '--is-inside-work-tree', timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _dirty_files():
    return [l for l in git('status', '--porcelain', '--untracked-files=no').splitlines() if l.strip()]


def version_info():
    if not is_git_checkout():
        return {'error': 'not a git checkout'}
    try:
        commit, date, subject = git('log', '-1', '--format=%H%n%cI%n%s').split('\n', 2)
        return {
            'commit': commit,
            'short': commit[:7],
            'date': date,
            'subject': subject,
            'branch': git('rev-parse', '--abbrev-ref', 'HEAD'),
            'dirty': bool(_dirty_files()),
        }
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return {'error': str(e)}


def check(branch='master'):
    git('fetch', '--quiet', 'origin', branch, timeout=120)
    remote = f"origin/{branch}"
    return {
        'current': git('rev-parse', 'HEAD'),
        'remote': git('rev-parse', remote),
        'behind': int(git('rev-list', '--count', f"HEAD..{remote}")),
        'ahead': int(git('rev-list', '--count', f"{remote}..HEAD")),
        'commits': git('log', '--format=%h %s', '-20', f"HEAD..{remote}").splitlines(),
        'dirty_files': _dirty_files(),
    }


def update(branch='master', force=False):
    if not is_git_checkout():
        raise RuntimeError('Not a git checkout - reinstall with install.sh to enable updates')
    if read_json(STATE_FILE):
        raise RuntimeError('A previous update is still waiting for its health check')

    # the repo has historically been copied around with mode changes - don't treat those as local edits
    git('config', 'core.fileMode', 'false')
    status = check(branch)
    prev, new = status['current'], status['remote']
    if prev == new:
        return {'updated': False, 'commit': prev}
    if (status['dirty_files'] or status['ahead']) and not force:
        raise RuntimeError(f"Local changes would be lost ({len(status['dirty_files'])} modified files, "
                           f"{status['ahead']} local commits).  Use force to overwrite.")

    changed = git('diff', '--name-only', prev, new).splitlines()
    logger.warning(f"Updating {prev[:7]} -> {new[:7]} ({len(changed)} files changed)")
    git('reset', '--hard', new)
    try:
        if any('requirements' in f for f in changed):
            pip_install()
    except Exception:
        logger.exception("Dependency install failed, reverting update")
        git('reset', '--hard', prev)
        raise

    write_json(STATE_FILE, {'prev': prev, 'new': new, 'attempts': 0, 'ts': time.time()})
    clear_last_rollback()
    return {'updated': True, 'from': prev, 'to': new, 'changed': changed, 'commits': status['commits']}


def mark_healthy():
    ''' called once we're connected and have been up a while.  Returns the confirmed update, if there was one '''
    state = read_json(STATE_FILE)
    if state:
        os.remove(STATE_FILE)
        logger.warning(f"Update to {state.get('new', '')[:7]} confirmed healthy")
    return state


def pending_update():
    return read_json(STATE_FILE)


def last_rollback():
    return read_json(LAST_ROLLBACK_FILE)


def clear_last_rollback():
    if os.path.exists(LAST_ROLLBACK_FILE):
        os.remove(LAST_ROLLBACK_FILE)
