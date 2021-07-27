from urllib.request import urlretrieve
import urllib.parse

class DocumentHandler():
    def __init__(self):
        '''
            since we'll need to authenticate in some shape or form, this will happen here
        '''
        self.document_link = 'http://ship.local/api/documents'
        self.staging_document_link = 'http://shipstaging.local/api/documents'
        print("Doing all the setup-y document stuff")


    def get_document(self, doc_type, delivery_number, order_number=None, bundle_number=0):
        '''
            this will return a filename which will be stored temporarily
        '''


        filename = f"/home/pi/tmp_print/{doc_type}{delivery_number}_{bundle_number}.pdf"
        params = urllib.parse.urlencode({'document_type':doc_type, 'delivery_number': delivery_number, 'bundle_number': bundle_number})
        document_link = self.document_link
        if 'STAGING' in order_number:
            document_link = self.staging_document_link
        url = document_link + "?%s" % params
        print(url)
        try:
            res = urlretrieve(url, filename)
        except Exception as e:
            print("Document Handler error getting document")
            raise
        print(f"Download res was {res}, to {filename}")
        return filename



    def cleanup_document(self, filename):
        '''
            just do a straight up delete
        '''
        print(f"Deleting document {filename}")


if __name__ == '__main__':
    d = DocumentHandler()
    # d.get_document('delivery_number', '22')
