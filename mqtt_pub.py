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

'''

import paho.mqtt.client as mqtt
import json
import time
first = True
PRINTING_COMMAND_TOPIC = "popcorn/printing"

# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
    print("Connected with result code "+str(rc))

    for i in range(1):
        client.publish(PRINTING_COMMAND_TOPIC, payload=str(i), qos=0, retain=False)

    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    # client.subscribe(PRINTING_COMMAND_TOPIC)

# The callback for when a PUBLISH message is received from the server.
def on_message(client, userdata, msg):
    # if msg.topic == PRINTING_COMMAND_TOPIC:
    #     try:
    #         data = json.loads(msg.payload)
    #         if data['command'] and data['command'] == 'print':
    #             print("we're printing, baybeh")
    #
    #
    #
    #     except Exception as e:
    #         print(e)
    print(msg.topic+" "+str(msg.payload))
    # print("Starting long task")
    # if first:
    #     first = False
    #     time.sleep(25)
    #
    # print("Finished long task")

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

client.connect("broker.emqx.io", 1883, 60)

# Blocking call that processes network traffic, dispatches callbacks and
# handles reconnecting.
# Other loop*() functions are available that give a threaded interface and a
# manual interface.
client.loop_forever()
