'''
    Keeps the last few hundred log lines in memory so the fleet page can pull them over MQTT
    without needing journald permissions on the box.
'''
import collections
import logging

MAX_MSG_LEN = 2000


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity=500, error_capacity=50):
        super().__init__()
        self.records = collections.deque(maxlen=capacity)
        self.errors = collections.deque(maxlen=error_capacity)

    def emit(self, record):
        try:
            entry = {
                'ts': record.created,
                'level': record.levelname,
                'logger': record.name,
                'msg': self.format(record)[:MAX_MSG_LEN],
            }
        except Exception:
            self.handleError(record)
            return
        self.records.append(entry)
        if record.levelno >= logging.WARNING:
            self.errors.append(entry)

    def lines(self, count=200, min_level=logging.NOTSET):
        lines = [r for r in self.records if logging.getLevelName(r['level']) >= min_level]
        return lines[-count:]

    def recent_errors(self, count=10):
        return list(self.errors)[-count:]


buffer = RingBufferHandler()


def setup_logging(level=logging.INFO):
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    buffer.setFormatter(logging.Formatter('%(message)s'))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(stream)
    root.addHandler(buffer)
