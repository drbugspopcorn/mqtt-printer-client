'''
    We just need to connect, and wait for messages.

    On a message, print out either the invoice or the label as described.
    Need a way of setting up printers, and of printing the docs.

    Printing is likely easier on linux than Windows, so I'd be inclined to run this on a
    raspberry pi rather than a Windows 10 box.  I believe I can run it on the same



    Possibly also host a (very simple) web server that can edit the printer configuration
        -- Jokes, will just have an mqtt config channel set up which will allow users to query the printers connected, and
        set them up for a given label type/document.  I believe that CUPS will still be required to initially add the printer

    Test this out with http://tools.emqx.io/recent_connections/38353d9b-2e4c-4fdc-b73b-77b2e4e15635

    Broker at https://www.emqx.io/mqtt/public-mqtt5-broker

    Will need to figure out how we handle subscribes and handling printing jobs that aren't for us.  The front end itself will decided which jobs get routed to which printer,
    but we've got a few options.  We could segregate it by topics (popcorn/printing/PRINTERNAME) and only subscribe to the printers that we implement.  This would mean that we need
    to listen to a command channel (popcorn/printers/all) to listen out for printer enumerate calls, and then once we know we have certain printers, we listen out on that channel.  Perhaps it
    should be id-printer (rpi12-TSC or something like that)

    @TODO possibly need to handle the documents not being ready yet (possibly 425 Too Early?) from the document handler.  This will depend on how long it takes to create the reports, but it also is possible with the
    courier labels (a couple of seconds to generate the labels).  Probably only an issue if we decide to speed up the workflow on the frontend by throwing slower tasks to a task thread (courier and invoicing)


'''

import paho.mqtt.client as mqtt

from decouple import config

import json
import time

if config('TEST_ENVIRONMENT', default='') == 'WINDOWS':
    import mock_printer_handler as printer_handler
else:
    import printer_handler

import document_handler


# .env file defines BASE_CHANNEL.  Includes the trailing slash
PRINTING_PRINT_TOPIC = f"{config('BASE_CHANNEL')}{config('CLIENT_NAME')}"
PRINTING_COMMAND_TOPIC = f"{config('BASE_CHANNEL')}"

# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    print("Connected with result code "+str(rc))

    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    client.subscribe(PRINTING_PRINT_TOPIC)
    client.subscribe(PRINTING_COMMAND_TOPIC)

# The callback for when a PUBLISH message is received from the server.
def on_message(client, handlers, msg):
    try:            # we can't fall over, need to handle all our errors.  Perhaps chuck the error on an error channel
        if msg.topic == PRINTING_PRINT_TOPIC:
            try:
                raw = False
                data = json.loads(msg.payload)

                if 'url' in data and 'printer' in data:
                    raw = False
                    if 'raw' in data:
                        raw = data['raw']

                    file = handlers['docs'].get_document(data['url'])
                    handlers['print'].print(data['printer'], file, raw)
                    handlers['docs'].cleanup_document(file)

            except Exception as e:
                print(f"Error: Badly formed data or document not found {e}")

        elif msg.topic == PRINTING_COMMAND_TOPIC:
            try:
                data = json.loads(msg.payload)
                if 'command' in data and data['command'] == 'enumerate':
                    printers = handlers['print'].enumerate_printers()
                    printers_response = []
                    for p in printers:
                        printers_response.append(f"{config('BASE_CHANNEL')}{config('CLIENT_NAME')}/{p}")

                    client.publish(PRINTING_COMMAND_TOPIC, payload=json.dumps(printers_response))

            except Exception as e:
                print(f"Error: Bad command, or something malformed: {e}")

        print(msg.topic+" "+str(msg.payload))


    except Exception as e:
        #@TODO start logging errors on a logging collector
        print(f"ERROR: Unhandled exception!:{e}")


printer_handler = printer_handler.PrinterHandler()
document_handler = document_handler.DocumentHandler(config('DOCUMENT_LOCATION', default=""))
client = mqtt.Client(userdata={'print':printer_handler, 'docs': document_handler})
client.on_connect = on_connect
client.on_message = on_message

client.connect(config('MQTT_BROKER_ADDRESS'), config('MQTT_BROKER_PORT', cast=int), 60)

# Blocking call that processes network traffic, dispatches callbacks and
# handles reconnecting.
# Other loop*() functions are available that give a threaded interface and a
# manual interface.
client.loop_forever()
