from urllib.parse import unquote, urlsplit

import cups

# https://www.cups.org/doc/spec-ipp.html printer-type enum
CUPS_PRINTER_REMOTE = 0b10
PRINTER_STATES = {3: 'idle', 4: 'processing', 5: 'stopped'}
JOB_STATES = {3: 'pending', 4: 'held', 5: 'processing', 6: 'stopped', 7: 'canceled', 8: 'aborted', 9: 'completed'}

DIRECT_SCHEMES = ('usb', 'parallel', 'serial')
LOCAL_HOSTS = ('localhost', '127.0.0.1', '::1')


def connection_type(device_uri):
    '''
        'usb' for printers physically plugged into this box, 'network' for everything else we can identify.

        Modern USB printers (new Brothers etc.) are often driven through ipp-usb, which makes them look like
        network printers: ipp://localhost:60000/ipp/print, or a dnssd:// name ending "(USB)".
        cups-browsed's auto-created implicitclass:// queues for printers on the LAN count as network.
    '''
    if not device_uri:
        return 'unknown'
    parts = urlsplit(device_uri)
    scheme = parts.scheme.lower()
    if scheme in DIRECT_SCHEMES:
        return 'usb'
    if scheme == 'hp':      # HPLIP: hp:/usb/... or hp:/net/...
        return 'usb' if parts.path.startswith('/usb/') else 'network'
    if scheme in ('ipp', 'ipps', 'http', 'https') and (parts.hostname or '') in LOCAL_HOSTS:
        return 'usb'
    if scheme == 'dnssd' and '(USB)' in unquote(device_uri):
        return 'usb'
    return 'network'


DEFAULT_PDF_OPTIONS = {
    "fit-to-page": "true",
    "print-color-mode": "color",
    "media": "A6",  # Explicitly set size, don't auto-detect
    "PageSize": "A6",
}


class PrinterHandler():
    '''
        Opens a fresh CUPS connection per call - pycups connections aren't thread safe, and print jobs and
        fleet commands run on different threads.
    '''

    def __init__(self, connections=('usb',)):
        # which printers get offered to the OMS by enumerate - see PRINTER_CONNECTIONS in example.env
        self.connections = set(connections)

    def _conn(self):
        return cups.Connection()

    def print(self, printer, filename, raw=False, options=None):
        opts = {"RAW": "TRUE"} if raw else dict(DEFAULT_PDF_OPTIONS)
        if options:
            opts.update({str(k): str(v) for k, v in options.items()})
        return self._conn().printFile(printer, filename, "AUTO", opts)

    def _local_printers(self, conn):
        # shared printers from other boxes show up as remote - other clients already advertise those
        return {k: v for k, v in conn.getPrinters().items() if not v['printer-type'] & CUPS_PRINTER_REMOTE}

    def enumerate_printers(self):
        return [name for name, p in self._local_printers(self._conn()).items()
                if connection_type(p.get('device-uri')) in self.connections]

    def _require_printer(self, conn, name):
        if name not in self._local_printers(conn):
            raise ValueError(f"No local printer called {name!r}")

    # --- fleet management ---

    def printer_details(self):
        conn = self._conn()
        printers = self._local_printers(conn)
        default = conn.getDefault()
        queued = {}
        for job in self._jobs(conn, 'not-completed'):
            queued[job['printer']] = queued.get(job['printer'], 0) + 1
        return [{
            'name': name,
            'state': PRINTER_STATES.get(p.get('printer-state'), p.get('printer-state')),
            'state_message': p.get('printer-state-message') or '',
            'state_reasons': [r for r in p.get('printer-state-reasons', []) if r != 'none'],
            'accepting': p.get('printer-is-accepting-jobs', True),
            'shared': p.get('printer-is-shared', False),
            'device_uri': p.get('device-uri'),
            'connection': connection_type(p.get('device-uri')),
            'offered': connection_type(p.get('device-uri')) in self.connections,
            'make_model': p.get('printer-make-and-model'),
            'info': p.get('printer-info'),
            'location': p.get('printer-location'),
            'default': name == default,
            'queued_jobs': queued.get(name, 0),
        } for name, p in sorted(printers.items())]

    def _jobs(self, conn, which='not-completed', printer=None):
        attrs = ['job-id', 'job-name', 'job-state', 'job-state-reasons', 'job-printer-uri', 'time-at-creation',
                 'time-at-completed', 'job-originating-user-name', 'job-printer-state-message']
        jobs = []
        for job_id, j in conn.getJobs(which_jobs=which, my_jobs=False, requested_attributes=attrs).items():
            job_printer = (j.get('job-printer-uri') or '').rsplit('/', 1)[-1]
            if printer and job_printer != printer:
                continue
            jobs.append({
                'id': job_id,
                'printer': job_printer,
                'name': j.get('job-name'),
                'state': JOB_STATES.get(j.get('job-state'), j.get('job-state')),
                'state_reasons': j.get('job-state-reasons'),
                'message': j.get('job-printer-state-message'),
                'user': j.get('job-originating-user-name'),
                'created': j.get('time-at-creation'),
                'completed': j.get('time-at-completed'),
            })
        return sorted(jobs, key=lambda j: j['id'], reverse=True)

    def list_jobs(self, which='not-completed', printer=None, limit=50):
        return self._jobs(self._conn(), which, printer)[:limit]

    def cancel_job(self, job_id):
        self._conn().cancelJob(int(job_id), purge_job=False)

    def purge_jobs(self, printer):
        conn = self._conn()
        self._require_printer(conn, printer)
        conn.cancelAllJobs(name=printer, purge_jobs=True)

    def enable_printer(self, printer):
        ''' CUPS stops a queue after a backend error and it stays stopped until someone resumes it '''
        conn = self._conn()
        self._require_printer(conn, printer)
        conn.enablePrinter(printer)
        conn.acceptJobs(printer)

    def disable_printer(self, printer, reason=''):
        conn = self._conn()
        self._require_printer(conn, printer)
        conn.disablePrinter(printer, reason=reason)

    def test_print(self, printer):
        conn = self._conn()
        self._require_printer(conn, printer)
        return conn.printTestPage(printer)

    def list_devices(self, timeout=10):
        devices = self._conn().getDevices(timeout=timeout)
        return sorted([{
            'uri': uri,
            'class': d.get('device-class'),
            'info': d.get('device-info'),
            'make_model': d.get('device-make-and-model'),
            'id': d.get('device-id'),
        } for uri, d in devices.items()], key=lambda d: (d['class'] != 'direct', d['uri']))

    def list_drivers(self, search='', limit=200):
        terms = search.lower().split()
        drivers = []
        for ppd, d in self._conn().getPPDs().items():
            make_model = d.get('ppd-make-and-model', '')
            if all(t in f"{make_model} {ppd}".lower() for t in terms):
                drivers.append({'ppd': ppd, 'make_model': make_model, 'language': d.get('ppd-natural-language')})
        drivers.sort(key=lambda d: d['make_model'])
        return {'total': len(drivers), 'drivers': drivers[:limit]}

    def add_printer(self, name, uri, driver='everywhere', info='', location='', options=None, shared=False,
                    make_default=False):
        '''
            driver: 'everywhere' (driverless IPP), 'raw' (ZPL/label printers fed raw data), or a ppd name from list_drivers
        '''
        conn = self._conn()
        kwargs = {'device': uri, 'info': info or name, 'location': location}
        if driver and driver != 'raw':
            kwargs['ppdname'] = driver
        conn.addPrinter(name, **kwargs)
        conn.setPrinterShared(name, bool(shared))
        conn.enablePrinter(name)
        conn.acceptJobs(name)
        for option, value in (options or {}).items():
            conn.addPrinterOptionDefault(name, option, str(value))
        if make_default:
            conn.setDefault(name)

    def remove_printer(self, printer):
        conn = self._conn()
        self._require_printer(conn, printer)
        conn.deletePrinter(printer)

    def set_default(self, printer):
        conn = self._conn()
        self._require_printer(conn, printer)
        conn.setDefault(printer)

    def set_options(self, printer, options):
        conn = self._conn()
        self._require_printer(conn, printer)
        for option, value in options.items():
            conn.addPrinterOptionDefault(printer, option, str(value))


if __name__ == '__main__':
    p = PrinterHandler()
    print(p.enumerate_printers())
