'''
    Windows printing through the print spooler (pywin32).

        ZPL / anything that isn't a PDF -> sent straight to the printer with the RAW datatype
        PDFs                            -> printed silently by SumatraPDF (tools\\SumatraPDF.exe, from install.ps1)

    What gets printed is decided by the content, not the 'raw' flag, so a PDF label sent with raw: true still
    goes through the driver rather than dumping PDF bytes onto a Zebra.

    Printer setup (add/remove) uses PowerShell's PrintManagement cmdlets.  Runs fine as LocalSystem under the
    service wrapper, but that account only sees printers installed on this machine - not ones mapped per user.
'''
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
from datetime import timezone

from decouple import config

from test_page import test_pdf, test_zpl

try:
    import win32print
except ImportError:     # lets the pure helpers below be imported/tested off Windows
    win32print = None

logger = logging.getLogger(__name__)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
INSTALL_DIR = os.path.dirname(APP_DIR)
SETTINGS_FILE = os.path.join(APP_DIR, 'printer_settings.json')
CREATE_NO_WINDOW = 0x08000000
ERROR_INVALID_DATATYPE = 1804

# PRINTER_STATUS_* (winspool.h)
PRINTER_STATUS_FLAGS = {
    0x1: 'paused', 0x2: 'error', 0x4: 'pending-deletion', 0x8: 'paper-jam', 0x10: 'paper-out',
    0x20: 'manual-feed', 0x40: 'paper-problem', 0x80: 'offline', 0x100: 'io-active', 0x200: 'busy',
    0x400: 'printing', 0x800: 'output-bin-full', 0x1000: 'not-available', 0x2000: 'waiting', 0x4000: 'processing',
    0x8000: 'initializing', 0x10000: 'warming-up', 0x20000: 'toner-low', 0x40000: 'no-toner', 0x80000: 'page-punt',
    0x100000: 'user-intervention', 0x200000: 'out-of-memory', 0x400000: 'door-open', 0x800000: 'server-unknown',
    0x1000000: 'power-save',
}
STOPPED_FLAGS = {'paused', 'error', 'paper-jam', 'paper-out', 'paper-problem', 'offline', 'not-available', 'no-toner',
                 'user-intervention', 'door-open', 'output-bin-full', 'out-of-memory'}
BUSY_FLAGS = {'printing', 'processing', 'busy', 'io-active'}
ATTRIBUTE_SHARED = 0x8
ATTRIBUTE_NETWORK = 0x10
ATTRIBUTE_WORK_OFFLINE = 0x400

# JOB_STATUS_*
JOB_STATUS_FLAGS = {
    0x1: 'paused', 0x2: 'error', 0x4: 'deleting', 0x8: 'spooling', 0x10: 'printing', 0x20: 'offline',
    0x40: 'paper-out', 0x80: 'printed', 0x100: 'deleted', 0x200: 'blocked', 0x400: 'user-intervention',
    0x800: 'restarting', 0x1000: 'complete', 0x2000: 'retained',
}

# Ports that don't lead to a physical printer: Print to PDF/XPS, OneNote, fax, Remote Desktop redirection
VIRTUAL_PORTS = re.compile(r'^(PORTPROMPT:|FILE:|NUL:?|SHRFAX:|XPSPORT:|TS\d+|NE\d+:|ONENOTE|MICROSOFT\.)', re.I)
DIRECT_PORTS = re.compile(r'^(USB\d+|DOT4_\d+|LPT\d+:?|COM\d+:?)$', re.I)
NETWORK_PORTS = re.compile(r'^(IP_|WSD-|HTTPS?://|\d{1,3}(\.\d{1,3}){3})', re.I)

SUMATRA_PAPER = {'a2': 'A2', 'a3': 'A3', 'a4': 'A4', 'a5': 'A5', 'a6': 'A6', 'letter': 'letter', 'legal': 'legal',
                 'tabloid': 'tabloid', 'statement': 'statement'}
# Drivers that take raw label languages - test prints go out as ZPL for these
LABEL_DRIVER = re.compile(r'zdesigner|zebra|zpl|generic / text', re.I)
RAW_DRIVER = 'Generic / Text Only'

# DEVMODE bits (wingdi.h) for setting a printer's default paper
DM_ORIENTATION, DM_PAPERSIZE, DM_PAPERLENGTH, DM_PAPERWIDTH = 0x1, 0x2, 0x4, 0x8
DMPAPER_USER = 256
DMORIENT_PORTRAIT = 1
DM_OUT_BUFFER, DM_IN_BUFFER = 2, 8
DC_PAPERS, DC_PAPERSIZE = 2, 3


def connection_type(port, attributes=0, port_info=None):
    '''
        'usb' for printers plugged into this machine (USB, parallel, serial), 'virtual' for Print to PDF and
        friends, 'network' for everything else.  port_info is {port name: (monitor, description)} from EnumPorts.
    '''
    port = (port or '').split(',')[0].strip()
    if port.startswith('\\\\'):
        return 'network'        # connection to a printer shared from another PC
    if DIRECT_PORTS.match(port):
        return 'usb'
    if VIRTUAL_PORTS.match(port):
        return 'virtual'
    monitor, description = (port_info or {}).get(port.upper(), ('', ''))
    described = f"{monitor} {description}".lower()
    if 'usb' in described:
        return 'usb'
    if NETWORK_PORTS.match(port) or 'tcp' in described or 'wsd' in described or attributes & ATTRIBUTE_NETWORK:
        return 'network'
    if 'local port' in described:
        return 'virtual'
    return 'network'    # named Standard TCP/IP ports etc - err on the side of not offering it


def printer_state(status, attributes=0):
    flags = [name for bit, name in PRINTER_STATUS_FLAGS.items() if status & bit]
    if attributes & ATTRIBUTE_WORK_OFFLINE:
        flags.append('use-printer-offline')
    if STOPPED_FLAGS.intersection(flags):
        state = 'stopped'
    elif BUSY_FLAGS.intersection(flags):
        state = 'processing'
    else:
        state = 'idle'
    return state, flags


def job_state(status):
    flags = [name for bit, name in JOB_STATUS_FLAGS.items() if status & bit]
    if {'error', 'offline', 'paper-out', 'blocked', 'user-intervention'}.intersection(flags):
        return 'stopped', flags
    if 'paused' in flags:
        return 'held', flags
    if {'printing', 'spooling', 'deleting'}.intersection(flags):
        return 'processing', flags
    if {'printed', 'complete'}.intersection(flags):
        return 'completed', flags
    return 'pending', flags


def named_paper(media):
    ''' SumatraPDF's name for a standard paper ('a6', 'iso_a6_105x148mm' -> 'A6'), or None '''
    key = (media or '').strip().lower().replace('iso_', '').replace('na_', '').split('_')[0]
    return SUMATRA_PAPER.get(key)


def custom_size_mm(media):
    '''
        A label size that isn't one of SumatraPDF's named papers, as (width, height) in mm, e.g.
        '100x174mm', 'Custom.100x174mm' (CUPS), '4x6in', 'na_index-4x6_4x6in' (IPP).  None for 'A6' etc.
    '''
    media = (media or '').strip().lower()
    if not media or named_paper(media):
        return None
    sizes = re.findall(r'(\d+(?:\.\d+)?)\s*[x\u00d7]\s*(\d+(?:\.\d+)?)\s*(mm|in)?', media)
    if not sizes:
        return None
    width, height, unit = sizes[-1]
    scale = 25.4 if unit == 'in' else 1
    width, height = round(float(width) * scale, 1), round(float(height) * scale, 1)
    if not (10 <= width <= 1000 and 10 <= height <= 2000):
        return None
    return width, height


def sumatra_settings(options):
    '''
        Turns CUPS-style options (what the OMS and fleet page send) into SumatraPDF -print-settings.
        https://www.sumatrapdfreader.org/docs/Command-line-arguments
    '''
    opts = {str(k).lower(): str(v).strip() for k, v in (options or {}).items()}
    if opts.get('sumatra'):
        return opts['sumatra']
    scaling = opts.get('fit-to-page', opts.get('scaling', 'true')).lower()
    settings = [{'false': 'noscale', 'noscale': 'noscale', 'none': 'noscale', 'shrink': 'shrink'}.get(scaling, 'fit')]
    media = (opts.get('media') or opts.get('pagesize') or opts.get('paper') or '').lower()
    if named_paper(media):
        settings.append(f"paper={named_paper(media)}")
    # custom sizes (100x174mm) can't be passed to SumatraPDF - they're set as the printer's default paper instead
    color = (opts.get('print-color-mode') or opts.get('color') or '').lower()
    if color:
        settings.append('monochrome' if color in ('monochrome', 'mono', 'grayscale', 'greyscale', 'bw') else 'color')
    sides = opts.get('sides', '').lower()
    if sides:
        settings.append({'two-sided-long-edge': 'duplexlong', 'two-sided-short-edge': 'duplexshort'}.get(sides, 'simplex'))
    if opts.get('copies', '').isdigit() and int(opts['copies']) > 1:
        settings.append(f"{int(opts['copies'])}x")
    if opts.get('page-ranges'):
        settings.append(opts['page-ranges'])
    return ','.join(settings)


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def powershell(script, timeout=120):
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command',
         "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'; " + script],
        capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    if result.returncode != 0:
        # PowerShell errors come with several lines of position info - the first line is the useful bit
        lines = [l.strip() for l in (result.stderr or result.stdout).splitlines() if l.strip()]
        message = next((l for l in lines if not l.startswith(('+', 'At line', 'At char'))), 'PowerShell command failed')
        raise RuntimeError(message)
    return result.stdout


def port_for_uri(uri):
    '''
        returns (port name, PowerShell to create it or None).
        port:USB001 | socket://192.168.1.50[:9100] | 192.168.1.50 | lpd://host/queue
    '''
    uri = uri.strip()
    if uri.lower().startswith('port:'):
        return uri[5:], None
    match = re.match(r'^(?:socket|raw)://([^/:]+)(?::(\d+))?/?$', uri, re.I) or re.match(r'^([\w.-]+)(?::(\d+))?$', uri)
    if match:
        host, port = match.group(1), int(match.group(2) or 9100)
        name = f"IP_{host}" if port == 9100 else f"IP_{host}_{port}"
        return name, (f"if (-not (Get-PrinterPort -Name {ps_quote(name)} -ErrorAction SilentlyContinue)) "
                      f"{{ Add-PrinterPort -Name {ps_quote(name)} -PrinterHostAddress {ps_quote(host)} -PortNumber {port} }}")
    match = re.match(r'^lpd://([^/]+)/(.+)$', uri, re.I)
    if match:
        host, queue = match.groups()
        name = f"LPR_{host}_{queue}"
        return name, (f"if (-not (Get-PrinterPort -Name {ps_quote(name)} -ErrorAction SilentlyContinue)) "
                      f"{{ Add-PrinterPort -Name {ps_quote(name)} -LprHostAddress {ps_quote(host)} "
                      f"-LprQueueName {ps_quote(queue)} -LprByteCounting }}")
    raise ValueError("On Windows use a port from the device list, socket://<ip>:9100, or lpd://<ip>/<queue>")


def _get(d, *keys, default=None):
    ''' pywin32 has used both pPortName and PortName style keys over the years '''
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


def _timestamp(value):
    if value is None:
        return None
    try:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)     # the spooler reports UTC
        return value.timestamp()
    except (AttributeError, ValueError, OverflowError):
        return None


class PrinterHandler():
    def __init__(self, connections=('usb',)):
        # which printers get offered to the OMS by enumerate - see PRINTER_CONNECTIONS in example.env
        self.connections = set(connections)
        self.settings_lock = threading.Lock()
        self.paper_lock = threading.Lock()
        self.paper_sizes = {}       # (printer, driver paper number) -> (x, y) in 0.1mm

    # --- helpers ---

    def _sumatra(self):
        candidates = [
            config('SUMATRA_PATH', default=''),
            os.path.join(INSTALL_DIR, 'tools', 'SumatraPDF.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'SumatraPDF', 'SumatraPDF.exe'),
            os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'SumatraPDF', 'SumatraPDF.exe'),
        ]
        return next((c for c in candidates if c and os.path.isfile(c)), None)

    def _open(self, name, admin=False):
        if admin:
            return win32print.OpenPrinter(name, {'DesiredAccess': win32print.PRINTER_ALL_ACCESS})
        return win32print.OpenPrinter(name)

    def _ports(self):
        try:
            ports = win32print.EnumPorts(None, 2)
        except Exception:
            return {}
        info = {}
        for p in ports:
            name = _get(p, 'pPortName', 'PortName', 'Name', default='')
            info[name.upper()] = (_get(p, 'pMonitorName', 'MonitorName', default=''),
                                  _get(p, 'pDescription', 'Description', default=''))
        return info

    def _printers(self):
        '''
            Printers installed on this PC.  Connections to printers shared from elsewhere (\\\\server\\name,
            \\\\http://host:631\\name) are left out: the spooler asks the remote end about those, and when it's
            switched off each call blocks for Windows' 21s connect timeout, which stalls the whole client (MQTT
            included) and gets it dropped by the broker.  The service can't print to them anyway.  Level 4 only lists
            names, without contacting anything, so connections are skipped before anything asks them for details.
        '''
        printers = {}
        for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL, None, 4):
            name = p['pPrinterName']
            if name.startswith('\\\\') or p.get('pServerName'):
                continue
            try:
                handle = self._open(name)
                try:
                    printers[name] = win32print.GetPrinter(handle, 2)
                finally:
                    win32print.ClosePrinter(handle)
            except Exception as e:      # removed between the two calls
                logger.debug(f"Skipping {name}: {e}")
        return printers

    def _require_printer(self, name):
        printers = self._printers()
        if name not in printers:
            raise ValueError(f"No printer called {name!r} on this PC")
        return printers[name]

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_settings(self, settings):
        tmp = SETTINGS_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(settings, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)

    def warnings(self):
        if not self._sumatra():
            return ['SumatraPDF not found - PDFs can\'t print.  Re-run install.ps1 or set SUMATRA_PATH']
        return []

    # --- printing ---

    def print(self, printer, filename, raw=False, options=None):
        self._require_printer(printer)
        with open(filename, 'rb') as f:
            data = f.read()
        if data.lstrip()[:5] == b'%PDF-':
            if raw:
                logger.info(f"Job for {printer} was flagged raw but is a PDF - printing it through the driver")
            merged = dict(self._load_settings().get(printer, {}), **(options or {}))
            return self._print_pdf(printer, filename, merged)
        return self._print_raw(printer, data, os.path.basename(filename))

    def _print_raw(self, printer, data, document_name='Label'):
        handle = self._open(printer)
        try:
            try:
                job_id = win32print.StartDocPrinter(handle, 1, (document_name, None, 'RAW'))
            except Exception as e:
                if getattr(e, 'winerror', None) == ERROR_INVALID_DATATYPE or (e.args and e.args[0] == ERROR_INVALID_DATATYPE):
                    raise RuntimeError(f"{printer}'s driver won't accept raw data (probably a v4/XPS driver). Use the "
                                       f"manufacturer's driver (ZDesigner for Zebras) or '{RAW_DRIVER}'") from e
                raise
            try:
                win32print.StartPagePrinter(handle)
                win32print.WritePrinter(handle, data)
                win32print.EndPagePrinter(handle)
            finally:
                win32print.EndDocPrinter(handle)
        finally:
            win32print.ClosePrinter(handle)
        return job_id

    def _print_pdf(self, printer, filename, options):
        sumatra = self._sumatra()
        if not sumatra:
            raise RuntimeError('SumatraPDF not found - re-run install.ps1 or set SUMATRA_PATH in .env')
        size = custom_size_mm(options.get('media') or options.get('pagesize') or options.get('paper'))
        problem = size and self._apply_paper(printer, *size)
        if problem:
            logger.warning(problem)
        settings = sumatra_settings(options)
        cmd = [sumatra, '-print-to', printer, '-print-settings', settings, '-silent', filename]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, creationflags=CREATE_NO_WINDOW)
        if result.returncode != 0:
            raise RuntimeError(f"SumatraPDF couldn't print to {printer} (exit {result.returncode}) "
                               f"{(result.stderr or result.stdout).strip()}".strip())
        logger.info(f"Printed {filename} on {printer} via SumatraPDF ({settings})")
        return None

    def _apply_paper(self, printer, width_mm, height_mm):
        '''
            Makes width x height mm the printer's default paper, which SumatraPDF picks up when it isn't given
            paper=.  Set as both the machine-wide "Printing Defaults" and the service account's own preferences:
            the size you pick in Printing Preferences on the desktop only applies to your user, so the service
            never sees it.  Uses the driver's own paper if it has one that size, else a user-defined size.
            Returns an error message if the driver didn't take the size.
        '''
        width, length = int(round(width_mm * 10)), int(round(height_mm * 10))     # DEVMODE uses 0.1mm
        with self.paper_lock:
            handle = self._open(printer, admin=True)
            try:
                info = win32print.GetPrinter(handle, 2)
                devmode = info.get('pDevMode')
                if devmode is None:
                    raise RuntimeError(f"{printer}'s driver didn't give us its settings to change")
                current = self._devmode(handle) or devmode
                if self._paper_mm(printer, info['pPortName'], current) == (width / 10, length / 10) \
                        and current.Orientation == DMORIENT_PORTRAIT:
                    return None
                paper = self._driver_paper(printer, info['pPortName'], width, length)
                devmode.Fields |= DM_PAPERSIZE | DM_ORIENTATION
                devmode.Orientation = DMORIENT_PORTRAIT
                if paper:
                    devmode.PaperSize = paper
                    devmode.Fields &= ~(DM_PAPERWIDTH | DM_PAPERLENGTH)
                else:
                    devmode.PaperSize = DMPAPER_USER
                    devmode.PaperWidth, devmode.PaperLength = width, length
                    devmode.Fields |= DM_PAPERWIDTH | DM_PAPERLENGTH
                # let the driver merge the change into its private settings (Zebra keeps label size there too)
                win32print.DocumentProperties(0, handle, printer, devmode, devmode, DM_IN_BUFFER | DM_OUT_BUFFER)
                info['pDevMode'] = devmode
                info['pSecurityDescriptor'] = None
                win32print.SetPrinter(handle, 2, info, 0)
                try:
                    win32print.SetPrinter(handle, 9, {'pDevMode': devmode}, 0)
                except Exception as e:
                    logger.debug(f"Couldn't set per-user paper for {printer}: {e}")
                accepted = self._paper_mm(printer, info['pPortName'], devmode)
            finally:
                win32print.ClosePrinter(handle)
        if accepted and (abs(accepted[0] - width / 10) > 1 or abs(accepted[1] - length / 10) > 1):
            return (f"{printer}'s driver turned {width_mm:g}x{height_mm:g}mm into {accepted[0]:g}x{accepted[1]:g}mm - "
                    f"add a {width_mm:g}x{height_mm:g}mm label size to the driver, then pick it again")
        logger.info(f"Default paper on {printer} is now {width_mm:g}x{height_mm:g}mm")
        return None

    def _driver_papers(self, printer, port):
        ''' [(paper number, (x, y) in 0.1mm)] that the driver offers '''
        try:
            papers = win32print.DeviceCapabilities(printer, port, DC_PAPERS) or []
            sizes = win32print.DeviceCapabilities(printer, port, DC_PAPERSIZE) or []
        except Exception:
            return []
        return [(paper, (size['x'], size['y']) if isinstance(size, dict) else tuple(size))
                for paper, size in zip(papers, sizes)]

    def _driver_paper(self, printer, port, width, length):
        ''' the driver's paper number for this size (within 1mm), so drivers that ignore custom sizes still work '''
        for paper, (x, y) in self._driver_papers(printer, port):
            if paper != DMPAPER_USER and abs(x - width) <= 10 and abs(y - length) <= 10:
                return paper
        return None

    def _devmode(self, handle):
        ''' the settings the service account prints with: its own preferences if it has any, else Printing Defaults '''
        try:
            devmode = win32print.GetPrinter(handle, 9).get('pDevMode')
            if devmode is not None:
                return devmode
        except Exception:
            pass
        return win32print.GetPrinter(handle, 2).get('pDevMode')

    def _paper_mm(self, printer, port, devmode):
        ''' (width, height) in mm of the paper this DEVMODE names, before orientation; None if unknown '''
        if devmode.PaperSize == DMPAPER_USER or devmode.Fields & (DM_PAPERWIDTH | DM_PAPERLENGTH):
            if devmode.PaperWidth and devmode.PaperLength:
                return devmode.PaperWidth / 10, devmode.PaperLength / 10
        key = (printer, devmode.PaperSize)
        if key not in self.paper_sizes:
            self.paper_sizes.update({(printer, paper): size for paper, size in self._driver_papers(printer, port)})
        size = self.paper_sizes.setdefault(key, None)
        return (size[0] / 10, size[1] / 10) if size else None

    def paper_size(self, printer, port):
        ''' the size PDFs actually come out at on this printer, e.g. '100x174mm' - shown on the fleet page '''
        try:
            handle = self._open(printer)
            try:
                devmode = self._devmode(handle)
                size = devmode and self._paper_mm(printer, port, devmode)
            finally:
                win32print.ClosePrinter(handle)
        except Exception:
            return None
        if not size:
            return None
        if devmode.Orientation == 2:        # landscape
            size = (size[1], size[0])
        return f"{size[0]:g}x{size[1]:g}mm"

    def enumerate_printers(self):
        ports = self._ports()
        return [name for name, p in self._printers().items()
                if connection_type(p['pPortName'], p.get('Attributes', 0), ports) in self.connections]

    # --- fleet management ---

    def printer_details(self):
        ports = self._ports()
        settings = self._load_settings()
        try:
            default = win32print.GetDefaultPrinter()
        except Exception:
            default = None
        details = []
        for name, p in sorted(self._printers().items()):
            attributes = p.get('Attributes', 0)
            state, flags = printer_state(p.get('Status', 0), attributes)
            connection = connection_type(p['pPortName'], attributes, ports)
            problems = [f for f in flags if f in STOPPED_FLAGS or f in ('toner-low', 'use-printer-offline')]
            details.append({
                'name': name,
                'state': state,
                'state_message': ', '.join(f.replace('-', ' ') for f in problems).capitalize(),
                'state_reasons': flags,
                'accepting': not attributes & ATTRIBUTE_WORK_OFFLINE,
                'shared': bool(attributes & ATTRIBUTE_SHARED),
                'device_uri': f"port:{p['pPortName']}",
                'connection': connection,
                'offered': connection in self.connections,
                'make_model': p.get('pDriverName'),
                'info': p.get('pComment'),
                'location': p.get('pLocation'),
                'default': name == default,
                'queued_jobs': p.get('cJobs', 0),
                'options': settings.get(name, {}),
                'paper': self.paper_size(name, p['pPortName']),
            })
        return details

    def _jobs_for(self, printer):
        handle = self._open(printer)
        try:
            return win32print.EnumJobs(handle, 0, 999, 1)
        finally:
            win32print.ClosePrinter(handle)

    def list_jobs(self, which='not-completed', printer=None, limit=50):
        if which == 'completed':
            return []       # the spooler forgets jobs once they've printed
        jobs = []
        for name in ([printer] if printer else self._printers()):
            try:
                raw_jobs = self._jobs_for(name)
            except Exception as e:
                logger.warning(f"Couldn't read jobs for {name}: {e}")
                continue
            for j in raw_jobs:
                state, flags = job_state(j.get('Status', 0))
                jobs.append({
                    'id': j['JobId'],
                    'printer': name,
                    'name': j.get('pDocument'),
                    'state': state,
                    'state_reasons': flags,
                    'message': j.get('pStatus') or ', '.join(flags),
                    'user': j.get('pUserName'),
                    'created': _timestamp(j.get('Submitted')),
                    'completed': None,
                })
        return sorted(jobs, key=lambda j: j['id'], reverse=True)[:limit]

    def cancel_job(self, job_id):
        # job ids are unique across the spooler, so find which printer it's on
        job_id = int(job_id)
        for name in self._printers():
            try:
                if not any(j['JobId'] == job_id for j in self._jobs_for(name)):
                    continue
            except Exception:
                continue
            handle = self._open(name, admin=True)
            try:
                win32print.SetJob(handle, job_id, 0, None, win32print.JOB_CONTROL_DELETE)
            finally:
                win32print.ClosePrinter(handle)
            return
        raise ValueError(f"No queued job {job_id}")

    def _control(self, printer, command):
        self._require_printer(printer)
        handle = self._open(printer, admin=True)
        try:
            win32print.SetPrinter(handle, 0, None, command)
        finally:
            win32print.ClosePrinter(handle)

    def purge_jobs(self, printer):
        self._control(printer, win32print.PRINTER_CONTROL_PURGE)

    def enable_printer(self, printer):
        ''' resume a paused queue and untick "Use printer offline" '''
        self._control(printer, win32print.PRINTER_CONTROL_RESUME)
        handle = self._open(printer, admin=True)
        try:
            info = win32print.GetPrinter(handle, 2)
            if info['Attributes'] & ATTRIBUTE_WORK_OFFLINE:
                info['Attributes'] &= ~ATTRIBUTE_WORK_OFFLINE
                info['pSecurityDescriptor'] = None
                win32print.SetPrinter(handle, 2, info, 0)
        finally:
            win32print.ClosePrinter(handle)

    def disable_printer(self, printer, reason=''):
        self._control(printer, win32print.PRINTER_CONTROL_PAUSE)

    def test_print(self, printer):
        info = self._require_printer(printer)
        if LABEL_DRIVER.search(info.get('pDriverName') or ''):
            return self._print_raw(printer, test_zpl(printer), 'Printer test')
        fd, path = tempfile.mkstemp(prefix='printer_test_', suffix='.pdf')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(test_pdf(printer))
            return self._print_pdf(printer, path, self._load_settings().get(printer, {}))
        finally:
            os.remove(path)

    def list_devices(self, timeout=10):
        ''' Windows sets USB printers up itself on plug-in, so "devices" here are the ports a printer can use '''
        used = {}
        for name, p in self._printers().items():
            used.setdefault(p['pPortName'].upper(), []).append(name)
        devices = []
        for port, (monitor, description) in self._ports().items():
            kind = connection_type(port, 0, {port: (monitor, description)})
            if kind == 'virtual':
                continue
            label = f"{port} - {description or monitor}".strip(' -')
            if port in used:
                label += f" (used by {', '.join(used[port])})"
            devices.append({'uri': f"port:{port}", 'class': 'direct' if kind == 'usb' else 'network',
                            'info': label, 'make_model': description, 'id': ''})
        return sorted(devices, key=lambda d: (d['class'] != 'direct', d['uri']))

    def list_drivers(self, search='', limit=200):
        names = set()
        try:
            for d in win32print.EnumPrinterDrivers(None, None, 2):
                names.add(_get(d, 'Name', 'pName', default=''))
        except Exception as e:
            logger.warning(f"Couldn't list drivers: {e}")
        names.discard('')
        names.add(RAW_DRIVER)       # inbox driver - add_printer installs it on demand
        terms = search.lower().split()
        drivers = sorted(n for n in names if all(t in n.lower() for t in terms))
        return {'total': len(drivers), 'drivers': [{'ppd': n, 'make_model': n, 'language': ''} for n in drivers[:limit]]}

    def add_printer(self, name, uri, driver='raw', info='', location='', options=None, shared=False,
                    make_default=False):
        '''
            driver: 'raw' (Generic / Text Only - for ZPL printers fed raw), or an installed driver name from
            list_drivers.  There's no driverless option on Windows.
        '''
        if driver in (None, '', 'raw'):
            driver = RAW_DRIVER
        elif driver == 'everywhere':
            raise ValueError("Driverless printing isn't available on Windows - choose Raw or an installed driver")
        port, create_port = port_for_uri(uri)
        script = [
            create_port or '',
            f"if (-not (Get-PrinterDriver -Name {ps_quote(driver)} -ErrorAction SilentlyContinue)) "
            f"{{ Add-PrinterDriver -Name {ps_quote(driver)} }}",
            f"Add-Printer -Name {ps_quote(name)} -DriverName {ps_quote(driver)} -PortName {ps_quote(port)}"
            + (f" -Comment {ps_quote(info)}" if info else '') + (f" -Location {ps_quote(location)}" if location else '')
            + (f" -Shared -ShareName {ps_quote(name)}" if shared else ''),
        ]
        powershell('; '.join(s for s in script if s))
        if options:
            self.set_options(name, options)
        if make_default:
            self.set_default(name)

    def remove_printer(self, printer):
        self._require_printer(printer)
        powershell(f"Remove-Printer -Name {ps_quote(printer)}")
        with self.settings_lock:
            settings = self._load_settings()
            if settings.pop(printer, None) is not None:
                self._save_settings(settings)

    def rename_printer(self, printer, new_name):
        self._require_printer(printer)
        if new_name in self._printers():
            raise ValueError(f"There's already a printer called {new_name!r}")
        powershell(f"Rename-Printer -Name {ps_quote(printer)} -NewName {ps_quote(new_name)}")
        with self.settings_lock:
            settings = self._load_settings()
            if printer in settings:
                settings[new_name] = settings.pop(printer)
                self._save_settings(settings)

    def set_default(self, printer):
        ''' only affects the account the client runs as (LocalSystem under the service) '''
        self._require_printer(printer)
        win32print.SetDefaultPrinter(printer)

    def set_options(self, printer, options):
        '''
            PDF defaults for this printer (paper size, scaling, colour) - stored locally and applied by SumatraPDF.
            A custom media size like '100x174mm' is also written into the printer's own default paper straight away.
        '''
        self._require_printer(printer)
        media = options.get('media')
        if media and not named_paper(media):
            size = custom_size_mm(media)
            if not size:
                raise ValueError(f"Unknown paper size {media!r} - use A4/A5/A6/Letter/Legal or a size like 100x174mm")
            problem = self._apply_paper(printer, *size)
            if problem:
                raise RuntimeError(problem)
        with self.settings_lock:
            settings = self._load_settings()
            current = settings.get(printer, {})
            for option, value in options.items():
                if value in (None, ''):
                    current.pop(option, None)
                else:
                    current[option] = str(value)
            settings[printer] = current
            self._save_settings(settings)


if __name__ == '__main__':
    p = PrinterHandler(('usb', 'network'))
    print(p.enumerate_printers())
    print(json.dumps(p.printer_details(), indent=2, default=str))
