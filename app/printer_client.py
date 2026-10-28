'''
    MQTT printer client.  Runs on a box with printers attached (Pi, Ubuntu, Windows at a push) and prints whatever
    the OMS sends it, so any browser - phone, iPad, another PC - can print to printers plugged in here.

    Topics (BASE_CHANNEL=despatch/printers/, FLEET_CHANNEL=despatch/clients/):

    Printing (unchanged, the OMS frontend depends on these)
        despatch/printers/                    <- {"command": "enumerate"}
                                              -> ["despatch/printers/<client>/<printer>", ...]
        despatch/printers/<client>            <- {"printer", "url", "raw", "options"?}

    Fleet management
        despatch/clients/<client>/online      -> {"online": bool, "reason", "ts"}  retained, last will marks us offline
        despatch/clients/<client>/status      -> heartbeat every STATUS_INTERVAL, retained.  See build_status()
        despatch/clients/<client>/cmd         <- commands, see commands.py
        despatch/clients/_all/cmd             <- same, broadcast to every client
        despatch/clients/<client>/result      -> command results
        despatch/clients/<client>/events      -> print job outcomes as they happen
'''
import collections
import json
import logging
import os
import platform
import queue
import signal
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import paho.mqtt.client as mqtt
from decouple import config

import document_handler
import log_buffer
import system_info
import updater
from commands import CommandHandler

logger = logging.getLogger('printer_client')

# DEMO_MODE (dev only) shows prints in a web page instead - see demo_printer_handler.py
DEMO_MODE = config('DEMO_MODE', default=False, cast=bool)
PRINTER_HANDLER = config('PRINTER_HANDLER',
                         default='demo' if DEMO_MODE else 'windows' if platform.system() == 'Windows' else 'cups')
if PRINTER_HANDLER == 'windows':
    import printer_handler_windows as printer_handler
elif PRINTER_HANDLER == 'mock':
    import mock_printer_handler as printer_handler
elif PRINTER_HANDLER == 'demo':
    import demo_printer_handler as printer_handler
else:
    import printer_handler_cups as printer_handler

CLIENT_NAME = config('CLIENT_NAME', default=socket.gethostname().split('.')[0])
# .env file defines BASE_CHANNEL.  Includes the trailing slash
BASE_CHANNEL = config('BASE_CHANNEL', default='despatch/printers/')
FLEET_CHANNEL = config('FLEET_CHANNEL', default='despatch/clients/')
STATUS_INTERVAL = config('STATUS_INTERVAL', default=30, cast=int)
PRINTER_CONNECTIONS = config('PRINTER_CONNECTIONS', default='usb',
                             cast=lambda v: [c.strip() for c in v.split(',') if c.strip()])
MQTT_BROKER_ADDRESS = config('MQTT_BROKER_ADDRESS')
MQTT_BROKER_PORT = config('MQTT_BROKER_PORT', default=1883, cast=int)

PRINTING_PRINT_TOPIC = f"{BASE_CHANNEL}{CLIENT_NAME}"
PRINTING_COMMAND_TOPIC = f"{BASE_CHANNEL}"
CLIENT_TOPIC = f"{FLEET_CHANNEL}{CLIENT_NAME}/"
ONLINE_TOPIC = CLIENT_TOPIC + 'online'
STATUS_TOPIC = CLIENT_TOPIC + 'status'
CMD_TOPIC = CLIENT_TOPIC + 'cmd'
RESULT_TOPIC = CLIENT_TOPIC + 'result'
EVENTS_TOPIC = CLIENT_TOPIC + 'events'
BROADCAST_CMD_TOPIC = f"{FLEET_CHANNEL}_all/cmd"


class PrinterClient():
    def __init__(self):
        self.started_at = time.time()
        self.printers = (printer_handler.PrinterHandler(PRINTER_CONNECTIONS) if PRINTER_HANDLER == 'cups'
                         else printer_handler.PrinterHandler())
        self.docs = document_handler.DocumentHandler(config('DOCUMENT_LOCATION', default=''))
        self.commands = CommandHandler(self)
        self.version = updater.version_info()

        self.print_queue = queue.Queue()
        self.command_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='cmd')
        self.recent_jobs = collections.deque(maxlen=20)
        self.job_stats = {'printed': 0, 'failed': 0, 'last_ok_at': None, 'last_error_at': None}
        self.connected_at = None
        self.status_wanted = threading.Event()
        self.exit_code = None

        self.client = mqtt.Client(client_id=f"printer-client-{CLIENT_NAME}",
                                  callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        if config('MQTT_USERNAME', default=''):
            self.client.username_pw_set(config('MQTT_USERNAME'), config('MQTT_PASSWORD', default=''))
        self.client.will_set(ONLINE_TOPIC, json.dumps(self._online_payload(False, 'connection lost')), qos=1,
                             retain=True)
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    # --- mqtt plumbing ---

    def _online_payload(self, online, reason=''):
        return {'online': online, 'reason': reason, 'ts': time.time()}

    def publish(self, topic, data, retain=False, qos=0):
        return self.client.publish(topic, payload=json.dumps(data, default=str), qos=qos, retain=retain)

    # The callback for when the client receives a CONNACK response from the server.
    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error(f"Broker refused connection: {reason_code}")
            return
        logger.info(f"Connected to {MQTT_BROKER_ADDRESS}:{MQTT_BROKER_PORT} as {CLIENT_NAME}")
        self.connected_at = time.time()

        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        client.subscribe([(PRINTING_PRINT_TOPIC, 1), (PRINTING_COMMAND_TOPIC, 0), (CMD_TOPIC, 1),
                          (BROADCAST_CMD_TOPIC, 1)])
        self.publish(ONLINE_TOPIC, self._online_payload(True), qos=1, retain=True)
        self.request_status()
        self.announce_printers()

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected_at = None
        if self.exit_code is None:
            logger.warning(f"Disconnected from broker ({reason_code}), will retry")

    # The callback for when a PUBLISH message is received from the server.
    def on_message(self, client, userdata, msg):
        # we can't fall over, need to handle all our errors.  Anything slow goes to another thread so we keep
        # servicing the connection.
        try:
            if msg.topic == PRINTING_PRINT_TOPIC:
                self.queue_print(json.loads(msg.payload))
            elif msg.topic == PRINTING_COMMAND_TOPIC:
                data = json.loads(msg.payload)
                if isinstance(data, dict) and data.get('command') == 'enumerate':
                    self.announce_printers()
            elif msg.topic in (CMD_TOPIC, BROADCAST_CMD_TOPIC):
                data = json.loads(msg.payload)
                self.command_pool.submit(self.run_command, data)
        except (ValueError, TypeError) as e:
            logger.error(f"Badly formed message on {msg.topic}: {e} {msg.payload[:200]!r}")
        except Exception:
            logger.exception(f"Unhandled exception handling message on {msg.topic}")

    def announce_printers(self):
        try:
            printers = self.printers.enumerate_printers() or []
        except Exception:
            logger.exception("Couldn't enumerate printers")
            return
        self.publish(PRINTING_COMMAND_TOPIC, [f"{BASE_CHANNEL}{CLIENT_NAME}/{p}" for p in printers])

    # --- printing ---

    def queue_print(self, data):
        if not isinstance(data, dict) or 'url' not in data or 'printer' not in data:
            raise ValueError("print job needs 'url' and 'printer'")
        data['received'] = time.time()
        logger.info(f"Queued print {data['url']} on {data['printer']}")
        self.print_queue.put(data)

    def print_worker(self):
        while True:
            job = self.print_queue.get()
            started = time.time()
            record = {'printer': job['printer'], 'url': job['url'], 'raw': bool(job.get('raw')),
                      'received': job['received']}
            filename = None
            try:
                filename = self.docs.get_document(job['url'])
                record['cups_job_id'] = self.printers.print(job['printer'], filename, bool(job.get('raw')),
                                                            job.get('options'))
                record['ok'] = True
                self.job_stats['printed'] += 1
                self.job_stats['last_ok_at'] = time.time()
            except Exception as e:
                logger.exception(f"Print of {job['url']} on {job['printer']} failed")
                record['ok'] = False
                record['error'] = str(e) or e.__class__.__name__
                self.job_stats['failed'] += 1
                self.job_stats['last_error_at'] = time.time()
            finally:
                if filename:
                    self.docs.cleanup_document(filename)
            record['ts'] = time.time()
            record['duration'] = round(record['ts'] - started, 2)
            self.recent_jobs.appendleft(record)
            self.publish(EVENTS_TOPIC, dict(record, type='print'))
            if not record['ok']:
                self.request_status()

    # --- fleet ---

    def run_command(self, data):
        if not isinstance(data, dict):
            logger.error(f"Ignoring malformed command {data!r}")
            return
        self.publish(RESULT_TOPIC, self.commands.handle(data), qos=1)

    def request_status(self):
        self.status_wanted.set()

    def build_status(self):
        try:
            printers, cups_error = self.printers.printer_details(), None
        except Exception as e:
            logger.exception("Couldn't read printer state")
            printers, cups_error = [], str(e) or e.__class__.__name__
        return {
            'client': CLIENT_NAME,
            'ts': time.time(),
            'interval': STATUS_INTERVAL,
            'started_at': self.started_at,
            'connected_at': self.connected_at,
            'handler': PRINTER_HANDLER,
            'host': system_info.host_info(MQTT_BROKER_ADDRESS),
            'system': system_info.metrics(self.docs.document_location),
            'version': self.version,
            'update': {'pending': updater.pending_update(), 'last_rollback': updater.last_rollback()},
            'cups': {'ok': cups_error is None, 'error': cups_error},
            'printers': printers,
            'jobs': dict(self.job_stats, queued=self.print_queue.qsize(), recent=list(self.recent_jobs)[:10]),
            'errors': log_buffer.buffer.recent_errors(10),
        }

    def status_loop(self):
        while self.exit_code is None:
            if self.connected_at:
                try:
                    self.publish(STATUS_TOPIC, self.build_status(), retain=True)
                except Exception:
                    logger.exception("Failed to publish status")
                if updater.pending_update() and time.time() - self.started_at > updater.HEALTHY_AFTER_SECONDS:
                    updater.mark_healthy()
                    self.version = updater.version_info()
            self.status_wanted.wait(STATUS_INTERVAL)
            self.status_wanted.clear()

    def schedule_exit(self, reason, delay=1.0, after=None):
        ''' give the command result a moment to go out, say goodbye, then exit and let systemd restart us '''
        def go():
            time.sleep(delay)
            self.shutdown(reason, before_disconnect=after)
        threading.Thread(target=go, daemon=True).start()

    def shutdown(self, reason, before_disconnect=None):
        ''' must not run on the network loop thread - it waits for the offline message to be acked '''
        logger.warning(f"Shutting down: {reason}")
        self.exit_code = 0
        info = self.publish(ONLINE_TOPIC, self._online_payload(False, reason), retain=True, qos=1)
        try:
            info.wait_for_publish(timeout=3)
        except (RuntimeError, ValueError):
            pass
        # once we disconnect the main thread exits, taking this daemon thread with it
        if before_disconnect:
            before_disconnect()
        self.client.disconnect()

    def run(self):
        self.docs.purge_stale()
        threading.Thread(target=self.print_worker, name='print', daemon=True).start()
        threading.Thread(target=self.status_loop, name='status', daemon=True).start()
        signal.signal(signal.SIGTERM, lambda *_: self.schedule_exit('stopped', delay=0))

        logger.info(f"Starting {CLIENT_NAME} ({self.version.get('short', 'unknown version')}), "
                    f"broker {MQTT_BROKER_ADDRESS}:{MQTT_BROKER_PORT}")
        self.client.connect_async(MQTT_BROKER_ADDRESS, MQTT_BROKER_PORT, 60)
        # Blocking call that processes network traffic, dispatches callbacks and
        # handles reconnecting.
        self.client.loop_forever(retry_first_connection=True)
        return self.exit_code or 0


if __name__ == '__main__':
    log_buffer.setup_logging(config('LOG_LEVEL', default='INFO'))
    logging.getLogger('paho').setLevel(logging.WARNING)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    sys.exit(PrinterClient().run())
