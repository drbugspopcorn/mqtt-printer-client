from urllib.request import urlretrieve
import urllib.parse
from datetime import datetime

class DocumentHandler():
    def __init__(self, document_location):
        '''
            since we'll need to authenticate in some shape or form, this will happen here
        '''

        self.document_location = document_location
        print("Doing all the setup-y document stuff")


    def get_document(self, document_url):
        '''
            this will return a filename which will be stored temporarily
        '''

        now = datetime.now()
        filename = f"{self.document_location}{now.strftime('%d%m%Y_%H%M%S')}.pdf"
        try:
            res = urlretrieve(document_url, filename)
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
