from win32 import win32print
import win32

# Get a list of all printers with their names and descriptions
printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL)


for printer in printers:
    print(printer)

printer_name = 'ZPL Text TLP2844'
# printer_name = 'ZDesigner TLP 2844'

# Get a handle to the printer
hPrinter = win32print.OpenPrinter(printer_name)

# Get the default printer attributes
attributes = win32print.GetPrinter(hPrinter, 2)
print(attributes)

# Get the printer name
print(attributes['pPrinterName'])

# print a raw ZPL file to the printer
raw_data = bytes("^XA^MMT^PW799^LL1399^LS0^FT700,1331^A0B,50,50^FB1300,9,0,L,0^FH\^FDHello^FS^FT734,1331^A0B,46,45^FH\^FDOrder #1234^FS^PQ1,0,1,Y^XZ", encoding="utf-8")

# Send the raw data to the printer
win32print.StartDocPrinter(hPrinter, 1, ("test", None, "RAW"))
win32print.StartPagePrinter(hPrinter)
win32print.WritePrinter(hPrinter, raw_data)
win32print.EndPagePrinter(hPrinter)
win32print.EndDocPrinter(hPrinter)
win32print.ClosePrinter(hPrinter)
    
# print (win32.GetLastError())