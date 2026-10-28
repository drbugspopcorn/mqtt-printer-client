'''
    Test pages for printers where we can't lean on CUPS' own (Windows).  A plain single-page PDF for normal
    printers, and a ZPL label for label printers.
'''
import socket
import time


def _pdf_escape(text):
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def test_pdf(printer, width_pt=297.6, height_pt=419.5):
    ''' A6 by default (the size most of our documents are) - fit-to-page scales it up on bigger paper '''
    lines = [
        (22, 'Printer test page'),
        (12, f'Printer: {printer}'),
        (12, f'Client: {socket.gethostname()}'),
        (12, f'Printed: {time.strftime("%Y-%m-%d %H:%M:%S")}'),
        (10, 'If you can read this, PDF printing works.'),
    ]
    content = ['0.5 w 18 18 m %.1f 18 l %.1f %.1f l 18 %.1f l h S' % (width_pt - 18, width_pt - 18, height_pt - 18, height_pt - 18)]
    y = height_pt - 60
    for size, text in lines:
        content.append(f'BT /F1 {size} Tf 36 {y:.1f} Td ({_pdf_escape(text)}) Tj ET')
        y -= size + 14
    stream = '\n'.join(content).encode('latin-1', 'replace')

    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width_pt} {height_pt}] '
        f'/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>'.encode(),
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream',
    ]
    out = bytearray(b'%PDF-1.4\n')
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f'{number} 0 obj\n'.encode() + body + b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode()
    out += b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets)
    out += f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return bytes(out)


def test_zpl(printer):
    def field(text):
        return text.replace('^', ' ').replace('~', ' ')
    return (
        '^XA^CI28'
        '^CF0,50^FO40,40^FDPrinter test^FS'
        f'^CF0,28^FO40,110^FD{field(printer)}^FS'
        f'^FO40,150^FD{field(socket.gethostname())}^FS'
        f'^FO40,190^FD{time.strftime("%Y-%m-%d %H:%M:%S")}^FS'
        '^FO40,240^GB500,3,3^FS'
        '^BY3,2,100^FO40,270^BCN,100,Y,N,N^FD1234567890^FS'
        '^XZ'
    ).encode('utf-8')


if __name__ == '__main__':
    with open('test_page.pdf', 'wb') as f:
        f.write(test_pdf('Example printer'))
    print(test_zpl('Example printer').decode())
