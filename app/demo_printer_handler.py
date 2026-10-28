'''
    Dev-only "printer" that shows what was printed in a web page instead of on paper.  DEMO_MODE=true

    Registers DEMO_PRINTERS (default "Demo") like any other printer, so the OMS can pick it, and keeps the last
    DEMO_HISTORY jobs in memory for the page at http://localhost:DEMO_PORT - PDFs are shown inline, ZPL is rendered
    in the browser.
'''
import itertools
import logging
import threading
import time
import webbrowser

from decouple import config

import demo_server
import mock_printer_handler

logger = logging.getLogger(__name__)

DEMO_PRINTERS = config('DEMO_PRINTERS', default='Demo', cast=lambda v: [p.strip() for p in v.split(',') if p.strip()])
DEMO_HOST = config('DEMO_HOST', default='127.0.0.1')
DEMO_PORT = config('DEMO_PORT', default=8631, cast=int)
DEMO_HISTORY = config('DEMO_HISTORY', default=15, cast=int)
DEMO_OPEN_BROWSER = config('DEMO_OPEN_BROWSER', default=True, cast=bool)


def sniff(data):
    head = data[:2048].lstrip()
    if head.startswith(b'%PDF'):
        return 'pdf'
    if b'^XA' in data[:65536].upper():
        return 'zpl'
    if head[:4] in (b'\x89PNG',) or head[:3] == b'\xff\xd8\xff':
        return 'image'
    return 'text'


class PrinterHandler(mock_printer_handler.PrinterHandler):
    def __init__(self):
        super().__init__()
        url = f"http://{'localhost' if DEMO_HOST in ('127.0.0.1', '0.0.0.0') else DEMO_HOST}:{DEMO_PORT}"
        self.printers = {name: {'make_model': 'Demo printer (shows in browser)', 'device_uri': url, 'state': 'idle'}
                         for name in DEMO_PRINTERS}
        self.job_ids = itertools.count(1)
        self.store = demo_server.JobStore(DEMO_HISTORY)
        demo_server.start(self.store, DEMO_HOST, DEMO_PORT)
        logger.warning(f"DEMO MODE: printers {', '.join(DEMO_PRINTERS)} print to {url}")
        if DEMO_OPEN_BROWSER:
            threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    def print(self, printer, filename, raw=False, options=None):
        if printer not in self.printers:
            raise ValueError(f"No demo printer called {printer!r}")
        with open(filename, 'rb') as f:
            data = f.read()
        job_id = next(self.job_ids)
        kind = sniff(data)
        self.store.add({
            'id': job_id,
            'ts': time.time(),
            'printer': printer,
            'raw': raw,
            'options': options or {},
            'kind': kind,
            'size': len(data),
        }, data)
        logger.info(f"Demo printed job {job_id} ({kind}, {len(data)} bytes) on {printer}")
        return job_id

    def test_print(self, printer):
        data = (b"^XA^CF0,60^FO50,50^FDDemo test print^FS^CF0,30^FO50,130^FD" + time.strftime('%c').encode()
                + b"^FS^BY3^FO50,200^BCN,120,Y,N,N^FD123456789^FS^XZ")
        job_id = next(self.job_ids)
        self.store.add({'id': job_id, 'ts': time.time(), 'printer': printer, 'raw': True, 'options': {},
                        'kind': 'zpl', 'size': len(data), 'test': True}, data)
        return job_id


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    p = PrinterHandler()
    for path in sys.argv[1:]:
        p.print(DEMO_PRINTERS[0], path, raw=not path.endswith('.pdf'))
    p.test_print(DEMO_PRINTERS[0])
    threading.Event().wait()
