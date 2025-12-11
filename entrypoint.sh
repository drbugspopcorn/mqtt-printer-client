#!/bin/bash

# Create cups admin user
useradd -r -G lpadmin -M cupsadmin
echo "cupsadmin:cupsadmin" | chpasswd

# Run cupsd in foreground
exec cupsd -f