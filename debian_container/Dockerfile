FROM debian:bookworm-slim

# Use a closer mirror (change to your region if needed)
RUN echo "deb http://mirror.aarnet.edu.au/debian/ bookworm main" > /etc/apt/sources.list && \
    echo "deb http://mirror.aarnet.edu.au/debian/ bookworm-updates main" >> /etc/apt/sources.list

RUN dpkg --add-architecture i386 && \
    for i in 1 2 3; do \
        apt-get update && break || sleep 10; \
    done && \
    for i in 1 2 3; do \
        apt-get install -y libc6:i386 \
            cups \
            libcups2-dev \
            python3 \
            python3-pip \
            python3-venv \
            wget && \
        break || sleep 10; \
    done && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/spool/lpd

# # Add i386 architecture and install 32-bit libraries BEFORE installing Brother drivers
# RUN dpkg --add-architecture i386 && \
#     apt-get update && \
#     apt-get install -y libc6:i386 && \
#     rm -rf /var/lib/apt/lists/*

# Now install Brother drivers
RUN wget https://download.brother.com/welcome/dlf100434/hl3150cdncupswrapper-1.1.4-0.i386.deb && \
    wget https://download.brother.com/welcome/dlf100432/hl3150cdnlpr-1.1.2-1.i386.deb && \
    dpkg -i hl3150cdnlpr-1.1.2-1.i386.deb && \
    dpkg -i hl3150cdncupswrapper-1.1.4-0.i386.deb && \
    rm hl3150cdncupswrapper-1.1.4-0.i386.deb hl3150cdnlpr-1.1.2-1.i386.deb

# Set up venv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY app/requirements.common.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Copy CUPS configs with printer setup
COPY debian_container/cupsd.conf /etc/cups/cupsd.conf
COPY debian_container/printers.conf /etc/cups/printers.conf
COPY debian_container/ppd/ /etc/cups/ppd/

# Entrypoint to configure CUPS on startup
RUN useradd -r -G lpadmin -M cupsadmin && echo "cupsadmin:cupsadmin" | chpasswd

EXPOSE 631

COPY app /app
WORKDIR /app

ENTRYPOINT ["/bin/bash", "-c", "cupsd && python printer_client.py"]