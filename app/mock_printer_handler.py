'''
    Stand-in for CUPS so the client (and the fleet page) can be exercised on a dev machine.  PRINTER_HANDLER=mock
'''
import itertools
import logging

logger = logging.getLogger(__name__)


class PrinterHandler():
    def __init__(self):
        self.printers = {
            'GK420d_303': {'make_model': 'Zebra ZPL Label Printer', 'state': 'idle',
                           'device_uri': 'usb://Zebra%20Technologies/ZTC%20GK420d?serial=28J194603303'},
            'Zebra_Technologies_ZTC_GK420d': {'make_model': 'Local Raw Printer', 'state': 'stopped',
                                              'state_message': 'Paused - media out', 'queued_jobs': 2,
                                              'device_uri': 'usb://Zebra%20Technologies/ZTC%20GK420d?serial=28J194600871'},
            'Brother_HL_L3240CDW': {'make_model': 'Brother HL-L3240CDW series, driverless', 'state': 'idle', 'default': True,
                                    'device_uri': 'ipp://localhost:60000/ipp/print', 'connection': 'usb'},
            'Office_Ricoh': {'make_model': 'Ricoh IM C3000 PDF', 'state': 'idle', 'connection': 'network', 'offered': False,
                             'device_uri': 'socket://192.168.1.40:9100'},
        }
        self.job_ids = itertools.count(1)

    def print(self, printer, filename, raw=False, options=None):
        logger.info(f"Printing filename {filename} out on {printer}! raw={raw} options={options}")
        return next(self.job_ids)

    def enumerate_printers(self):
        return list(self.printers)

    def printer_details(self):
        return [{
            'name': name, 'state': p.get('state', 'idle'), 'state_message': p.get('state_message', ''),
            'state_reasons': [], 'accepting': True, 'shared': False, 'device_uri': p.get('device_uri'),
            'connection': p.get('connection', 'usb'), 'offered': p.get('offered', True), 'make_model': p.get('make_model'),
            'info': name, 'location': '', 'default': p.get('default', False), 'queued_jobs': p.get('queued_jobs', 0),
        } for name, p in self.printers.items()]

    def list_jobs(self, which='not-completed', printer=None, limit=50):
        return []

    def cancel_job(self, job_id):
        pass

    def purge_jobs(self, printer):
        pass

    def enable_printer(self, printer):
        self.printers[printer].update(state='idle', state_message='')

    def disable_printer(self, printer, reason=''):
        self.printers[printer]['state'] = 'stopped'

    def test_print(self, printer):
        return next(self.job_ids)

    def list_devices(self, timeout=10):
        return [{'uri': 'usb://Zebra%20Technologies/ZTC%20GK420t?serial=29A181402145', 'class': 'direct', 'info': 'Zebra Technologies ZTC GK420t',
                 'make_model': 'Zebra Technologies ZTC GK420t', 'id': 'MFG:Zebra Technologies;MDL:ZTC GK420t;SN:29A181402145;'},
                {'uri': 'usb://Zebra%20Technologies/ZTC%20ZD420-203dpi%20ZPL?serial=D4J203900116', 'class': 'direct',
                 'info': 'Zebra Technologies ZTC ZD420-203dpi ZPL', 'make_model': 'Zebra Technologies ZTC ZD420-203dpi ZPL', 'id': ''},
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

    def rename_printer(self, printer, new_name):
        if new_name in self.printers:
            raise ValueError(f"There's already a printer called {new_name!r}")
        self.printers[new_name] = self.printers.pop(printer)

    def set_default(self, printer):
        pass

    def set_options(self, printer, options):
        pass


if __name__ == '__main__':
    p = PrinterHandler()
    p.print('A4_CP475', 'docs_tmp/invoice22.pdf')
