import cups
class PrinterHandler():
    def __init__(self):
        print("Doing all the setup-y printer stuff")
        self.conn = cups.Connection()

    def print(self, printer, filename, raw=False):
        print(f"Printing filename {filename} out on {printer}!")
        opts = {}
        if raw:
            opts = {"RAW":"TRUE"}
        pid = self.conn.printFile(printer, filename, "AUTO", opts)

    def enumerate_printers(self):
        printers = self.conn.getPrinters()
        return printers.keys()

if __name__ == '__main__':
    p = PrinterHandler()
    p.print('A4_CP475', 'docs_tmp/invoice22.pdf')
