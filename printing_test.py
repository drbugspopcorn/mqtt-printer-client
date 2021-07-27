#  We have issues with Identity-H/CID fonts -- the invoices end up garbled.
#  Couple of interesting links: https://bugs.launchpad.net/ubuntu/+source/cups-pdf/+bug/820820/comments/12
#  https://bugs.launchpad.net/ubuntu/+source/cups-pdf/+bug/942866
# can possibly deal with it in the CUPS filter.  Will get my head around it.


import cups
conn = cups.Connection()
# printers = conn.getPrinters()
#
# for printer in printers:
#         print(printer, printers[printer]["device-uri"])
#
# printer = list(printers.keys())[0]
printer = 'TSC_TTP-244_Plus'

print(printer)
pid = conn.printFile(printer, './test_label_rotated.pdf', "Invoice", {})
