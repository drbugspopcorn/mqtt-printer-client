
class PrinterHandler():
    def __init__(self):
        print("Doing all the setup-y printer stuff")

    def print(self, printer, filename, raw=False):
        print(f"Printing filename {filename} out on {printer}!")

    def enumerate_printers(self):
        pass

if __name__ == '__main__':
    p = PrinterHandler()
    p.print('A4_CP475', 'docs_tmp/invoice22.pdf')
