from win32 import win32print
import win32
# import ghostscript


def print_zpl(zpl, printer_name):
    """
    Prints the given zpl string to the given printer.
    """
    hPrinter = win32print.OpenPrinter(printer_name)
    try:
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("test of raw data", None, "RAW"))
        try:
            win32print.StartPagePrinter(hPrinter)
            win32print.WritePrinter(hPrinter, zpl)
            win32print.EndPagePrinter(hPrinter)
        finally:
            win32print.EndDocPrinter(hPrinter)
    finally:
        win32print.ClosePrinter(hPrinter)


def print_pdf(pdf_path, printer_name):
    """
    Prints the given pdf file to the given printer.
    """


    hPrinter = win32print.OpenPrinter(printer_name)
    pdf_file = open(pdf_path, 'rb')

    try:
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("test of raw data", None, "RAW"))
        try:
            win32print.StartPagePrinter(hPrinter)
            win32print.WritePrinter(hPrinter, pdf_file.read())
            win32print.EndPagePrinter(hPrinter)
        finally:
            win32print.EndDocPrinter(hPrinter)
    finally:
        win32print.ClosePrinter(hPrinter)

# Get a list of all printers with their names and descriptions
printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL)


for printer in printers:
    print("Printer: ", printer[2])
    
printer_name = 'ZDesigner GK420t'
pdf_file = "C:\\Users\\ReubenPosthuma\\Downloads\\188.pdf"
# printer_name = 'ZDesigner TLP 2844'

# Get a handle to the printer
hPrinter = win32print.OpenPrinter(printer_name)

# Get the default printer attributes
attributes = win32print.GetPrinter(hPrinter, 2)
print(attributes)

# Get the printer name
print(attributes['pPrinterName'])

# print a raw ZPL file to the printer
raw_data = bytes("""CT~~CD,~CC^~CT~
^XA~TA000~JSN^LT0^MNW^MTD^PON^PMN^LH0,0^JMA^PR4,4~SD15^JUS^LRN^CI0^XZ
^XA
^MMT
^PW799
^LL1391
^LS0
^FO320,0^GFA,07680,07680,00060,:Z64:
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:FB98
^FT21,92^A0N,68,67^FH\^FD1 OF 1^FS
^FT21,162^A@N,25,24,TT0003M_^FH\^CI17^F8^FDOriginating branch: CHRISTCHURCH^FS^CI0
^FT538,162^A@N,25,24,TT0003M_^FH\^CI17^F8^FDCONNOTE_NUMBER^FS^CI0
^FT21,198^A@N,25,24,TT0003M_^FH\^CI17^F8^FDPhone: my_phone^FS^CI0
^FT297,192^A@N,25,24,TT0003M_^FH\^CI17^F8^FDwww.mainstream.co.nz^FS^CI0
^FT651,198^A@N,25,24,TT0003M_^FH\^CI17^F8^FD01/01/2029^FS^CI0
^FO0,217^GB799,0,4^FS
^FT21,261^A@N,25,24,TT0003M_^FH\^CI17^F8^FDDeliver To:^FS^CI0
^FT21,321^A@N,51,51,TT0003M_^FH\^CI17^F8^FDRECEIVER LINE 1^FS^CI0
^FT21,379^A@N,51,51,TT0003M_^FH\^CI17^F8^FDRECEIVER LINE 2^FS^CI0
^FT21,434^A@N,51,51,TT0003M_^FH\^CI17^F8^FDSUBURB^FS^CI0
^FT21,488^A@N,51,51,TT0003M_^FH\^CI17^F8^FDCITY^FS^CI0
^FT21,582^A@N,51,51,TT0003M_^FH\^CI17^F8^FDREGION^FS^CI0
^FO0,622^GB799,0,4^FS
^FT21,670^A0N,34,33^FH\^FDRecv Phone:^FS
^FT206,671^A@N,34,33,TT0003M_^FH\^CI17^F8^FDreceiver_phone^FS^CI0
^FT21,711^A@N,34,33,TT0003M_^FH\^CI17^F8^FDRecv Ref:^FS^CI0
^FT156,711^A@N,34,33,TT0003M_^FH\^CI17^F8^FDreciever_ref^FS^CI0
^FT21,769^A@N,34,33,TT0003M_^FH\^CI17^F8^FDmore_receiver_details^FS^CI0
^FO0,843^GB799,0,4^FS
^FT21,888^A@N,34,33,TT0003M_^FH\^CI17^F8^FDSender:^FS^CI0
^FT384,888^A@N,34,33,TT0003M_^FH\^CI17^F8^FDCust No:^FS^CI0
^FT522,888^A@N,34,33,TT0003M_^FH\^CI17^F8^FDcustomer_number^FS^CI0
^FT21,928^A@N,34,33,TT0003M_^FH\^CI17^F8^FDCUSTOMER_NAME^FS^CI0
^FT21,968^A@N,34,33,TT0003M_^FH\^CI17^F8^FDOrder No:^FS^CI0
^FT169,968^A@N,34,33,TT0003M_^FH\^CI17^F8^FDsender_ref^FS^CI0
^FT21,1030^A@N,34,33,TT0003M_^FH\^CI17^F8^FDPickup from: pickup_single_line^FS^CI0
^FT21,1092^A@N,34,33,TT0003M_^FH\^CI17^F8^FDCarrier: MAINSTREAM NZ LIMITED^FS^CI0
^FO0,1128^GB795,0,4^FS
^BY5,3,160^FT70,1308^BCN,,Y,N
^FD>;1700241268>64/1^FS
^PQ1,0,1,Y^XZ
""", encoding="utf-8")
print_zpl(raw_data, printer_name)
print_pdf(pdf_file, printer_name)

printer = win32print.GetDefaultPrinter()