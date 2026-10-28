'''
    Stand-in for CUPS so the client (and the fleet page) can be exercised on a dev machine.  PRINTER_HANDLER=mock
'''
import itertools
import logging

logger = logging.getLogger(__name__)


class PrinterHandler():
    def __init__(self):
        self.printers = {
            'Mock_Label': {'make_model': 'Mock ZPL label printer', 'device_uri': 'usb://Mock/Label', 'state': 'idle'},
            'Mock_A4': {'make_model': 'Mock laser', 'device_uri': 'ipp://mock-a4.local/ipp/print', 'state': 'idle'},
        }
        self.job_ids = itertools.count(1)

    def print(self, printer, filename, raw=False, options=None):
        logger.info(f"Printing filename {filename} out on {printer}! raw={raw} options={options}")
        return next(self.job_ids)

    def enumerate_printers(self):
        return list(self.printers)

    def printer_details(self):
        return [dict(name=name, state_message='', state_reasons=[], accepting=True, shared=False, info=name,
                     location='', default=False, queued_jobs=0, **p) for name, p in self.printers.items()]

    def list_jobs(self, which='not-completed', printer=None, limit=50):
        return []

    def cancel_job(self, job_id):
        pass

    def purge_jobs(self, printer):
        pass

    def enable_printer(self, printer):
        self.printers[printer]['state'] = 'idle'

    def disable_printer(self, printer, reason=''):
        self.printers[printer]['state'] = 'stopped'

    def test_print(self, printer):
        return next(self.job_ids)

    def list_devices(self, timeout=10):
        return [{'uri': 'usb://Zebra/ZD420', 'class': 'direct', 'info': 'Zebra ZD420', 'make_model': 'Zebra ZD420', 'id': ''},
                {'uri': 'dnssd://Brother%20HL-L3240CDW._ipp._tcp.local/', 'class': 'network', 'info': 'Brother HL-L3240CDW',
                 'make_model': 'Brother HL-L3240CDW', 'id': ''}]

    def list_drivers(self, search='', limit=200):
        drivers = [{'ppd': 'drv:///sample.drv/zebra.ppd', 'make_model': 'Zebra ZPL Label Printer', 'language': 'en'}]
        return {'total': len(drivers), 'drivers': drivers}

    def add_printer(self, name, uri, driver='everywhere', info='', location='', options=None, shared=False,
                    make_default=False):
        self.printers[name] = {'make_model': driver, 'device_uri': uri, 'state': 'idle'}

    def remove_printer(self, printer):
        self.printers.pop(printer)

    def set_default(self, printer):
        pass

    def set_options(self, printer, options):
        pass


if __name__ == '__main__':
    p = PrinterHandler()
    p.print('A4_CP475', 'docs_tmp/invoice22.pdf')
