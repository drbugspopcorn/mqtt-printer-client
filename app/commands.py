'''
    Fleet commands, sent from the OMS fleet page to <FLEET_CHANNEL><client>/cmd as
        {"id": "<anything, echoed back>", "action": "printers.add", "args": {...}}
    and answered on <FLEET_CHANNEL><client>/result as
        {"id", "action", "ok": true, "data": ...}  or  {"id", "action", "ok": false, "error": "..."}

    No auth yet (LAN only) - see README before exposing the broker anywhere else.
'''
import logging
import os
import re
import shutil
import subprocess

import log_buffer
import updater

logger = logging.getLogger(__name__)

# lpadmin rejects spaces, slashes and '#'; keep it to something that is also a sane MQTT topic segment
PRINTER_NAME_RE = re.compile(r'^[A-Za-z0-9_.-]{1,127}$')


class CommandHandler():
    def __init__(self, app):
        self.app = app
        self.printers = app.printers
        self.actions = {
            'ping': lambda args: {'pong': True},
            'status': lambda args: app.build_status(),
            'logs': self.logs,
            'restart': self.restart,
            'reboot': self.reboot,
            'update.check': lambda args: updater.check(args.get('branch', 'master')),
            'update': self.update,
            'printers.list': lambda args: self.printers.printer_details(),
            'printers.devices': lambda args: self.printers.list_devices(timeout=int(args.get('timeout', 10))),
            'printers.drivers': lambda args: self.printers.list_drivers(args.get('search', '')),
            'printers.add': self.add_printer,
            'printers.remove': self._changes_printers(lambda args: self.printers.remove_printer(args['printer'])),
            'printers.enable': self._changes_printers(lambda args: self.printers.enable_printer(args['printer'])),
            'printers.disable': self._changes_printers(
                lambda args: self.printers.disable_printer(args['printer'], args.get('reason', ''))),
            'printers.set_default': self._changes_printers(lambda args: self.printers.set_default(args['printer'])),
            'printers.set_options': lambda args: self.printers.set_options(args['printer'], args['options']),
            'printers.test': self._changes_printers(lambda args: {'job_id': self.printers.test_print(args['printer'])}),
            'jobs.list': lambda args: self.printers.list_jobs(args.get('which', 'not-completed'), args.get('printer'),
                                                              int(args.get('limit', 50))),
            'jobs.cancel': self._changes_printers(lambda args: self.printers.cancel_job(args['job_id'])),
            'jobs.purge': self._changes_printers(lambda args: self.printers.purge_jobs(args['printer'])),
        }

    def handle(self, message):
        request_id = message.get('id')
        action = message.get('action')
        args = message.get('args') or {}
        result = {'id': request_id, 'action': action}
        handler = self.actions.get(action)
        if not handler:
            return dict(result, ok=False, error=f"Unknown action {action!r}")
        logger.info(f"Command {action} {args}")
        try:
            return dict(result, ok=True, data=handler(args))
        except KeyError as e:
            return dict(result, ok=False, error=f"Missing argument {e}")
        except Exception as e:
            logger.exception(f"Command {action} failed")
            return dict(result, ok=False, error=str(e) or e.__class__.__name__)

    def _changes_printers(self, fn):
        ''' push a fresh status after anything that changes printer/queue state so the page updates straight away '''
        def wrapped(args):
            try:
                return fn(args)
            finally:
                self.app.request_status()
        return wrapped

    def logs(self, args):
        level = logging.getLevelName(str(args.get('level', 'NOTSET')).upper())
        return log_buffer.buffer.lines(int(args.get('lines', 200)), level if isinstance(level, int) else 0)

    def add_printer(self, args):
        if not PRINTER_NAME_RE.match(args['name']):
            raise ValueError("Printer name may only contain letters, numbers, '.', '_' and '-'")
        if not args['uri']:
            raise ValueError('A device URI is required')
        self.printers.add_printer(
            args['name'], args['uri'],
            driver=args.get('driver', 'everywhere'),
            info=args.get('info', ''),
            location=args.get('location', ''),
            options=args.get('options'),
            shared=args.get('shared', False),
            make_default=args.get('make_default', False),
        )
        self.app.request_status()
        # browsers holding printer lists from 'enumerate' need to hear about the new one
        self.app.announce_printers()
        return {'name': args['name']}

    def restart(self, args):
        self.app.schedule_exit('restart')
        return {'restarting': True}

    def reboot(self, args):
        if os.name == 'nt':
            # the service runs as LocalSystem, which may shut down
            self.app.schedule_exit('reboot', after=lambda: subprocess.run(
                ['shutdown', '/r', '/t', '5', '/c', 'Rebooted from the OMS fleet page']))
            return {'rebooting': True}
        if not shutil.which('sudo'):
            raise RuntimeError('sudo not available')
        # validate the sudoers rule now so the page gets a useful error rather than silence
        check = subprocess.run(['sudo', '-n', '-l', 'systemctl', 'reboot'], capture_output=True, text=True, timeout=10)
        if check.returncode != 0:
            raise RuntimeError('Not permitted to reboot - re-run install.sh to add the sudoers rule')
        self.app.schedule_exit('reboot', after=lambda: subprocess.run(['sudo', '-n', 'systemctl', 'reboot']))
        return {'rebooting': True}

    def update(self, args):
        result = updater.update(args.get('branch', 'master'), force=bool(args.get('force')))
        if result['updated']:
            self.app.schedule_exit('update')
        return result
