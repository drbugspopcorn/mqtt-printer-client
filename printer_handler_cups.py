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
        local_printer_list = []
        for k in printers.keys():
            if not printers[k]['printer-type'] & 0b10:      # docs - https://www.cups.org/doc/spec-ipp.html printer type enum
                local_printer_list.append(k)
        return local_printer_list

if __name__ == '__main__':
    p = PrinterHandler()
    print(p.enumerate_printers())
