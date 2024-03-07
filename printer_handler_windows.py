from win32 import win32print

class PrinterHandler():
    def __init__(self):
        print("Doing all the setup-y printer stuff")


    def print(self, printer, filename, raw=False):
        print(f"Printing filename {filename} out on {printer}!")
        opts = {}
        if raw:
            self._print_raw(printer, filename)
        else:
            raise NotImplementedError("Printing PDFs is not yet supported on Windows")

    def _print_raw(self, printer, filename):
        # grab the raw text from the file 
        with open(filename, 'r') as f:
            zpl = f.read()
            hPrinter = win32print.OpenPrinter(printer)
            try:
                hJob = win32print.StartDocPrinter(hPrinter, 1, ("ZPL", None, "RAW"))
                try:
                    win32print.StartPagePrinter(hPrinter)
                    win32print.WritePrinter(hPrinter, zpl)
                    win32print.EndPagePrinter(hPrinter)
                finally:
                    win32print.EndDocPrinter(hPrinter)
            finally:
                win32print.ClosePrinter(hPrinter)

    def enumerate_printers(self):
        printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL)
        printer_names = [printer[2] for printer in printers]
        return printer_names

if __name__ == '__main__':
    p = PrinterHandler()
    print(p.enumerate_printers())
