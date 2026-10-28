import glob
import logging
import os
import shutil
import socket
import tempfile
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# the OMS can fire the print before a courier label/invoice has finished generating
RETRYABLE_HTTP_CODES = (404, 425, 429, 500, 502, 503, 504)


class DocumentHandler():
    def __init__(self, document_location, timeout=30, retries=3):
        self.document_location = document_location or tempfile.gettempdir()
        self.timeout = timeout
        self.retries = retries
        os.makedirs(self.document_location, exist_ok=True)

    def get_document(self, document_url):
        '''
            downloads to a unique temp file and returns its filename.  Caller must cleanup_document() it.
        '''
        last_error = None
        for attempt in range(self.retries):
            if attempt:
                time.sleep(2 * attempt)
            try:
                return self._download(document_url)
            except urllib.error.HTTPError as e:
                if e.code not in RETRYABLE_HTTP_CODES:
                    raise
                last_error = e
            except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
                last_error = e
            logger.warning(f"Download attempt {attempt + 1}/{self.retries} failed for {document_url}: {last_error}")
        raise last_error

    def _download(self, document_url):
        fd, filename = tempfile.mkstemp(prefix=time.strftime('%Y%m%d_%H%M%S_'), suffix='.pdf',
                                        dir=self.document_location)
        try:
            with os.fdopen(fd, 'wb') as f, urllib.request.urlopen(document_url, timeout=self.timeout) as resp:
                shutil.copyfileobj(resp, f)
            if os.path.getsize(filename) == 0:
                raise ValueError(f"Empty document from {document_url}")
        except BaseException:
            self.cleanup_document(filename)
            raise
        logger.info(f"Downloaded {document_url} to {filename}")
        return filename

    def cleanup_document(self, filename):
        try:
            os.remove(filename)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Couldn't delete {filename}: {e}")

    def purge_stale(self, max_age_seconds=3600):
        ''' leftovers from crashes (and the years before cleanup actually deleted anything) '''
        cutoff = time.time() - max_age_seconds
        removed = 0
        for path in glob.glob(os.path.join(self.document_location, '*.pdf')):
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
        if removed:
            logger.info(f"Removed {removed} stale documents from {self.document_location}")
        return removed


if __name__ == '__main__':
    d = DocumentHandler('docs_tmp/')
    # d.get_document('http://...')
