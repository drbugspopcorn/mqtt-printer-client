cp printer-client.service /lib/systemd/system/printer-client.service
systemctl enable printer-client.service
systemctl daemon-reload