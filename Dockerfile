FROM debian:bookworm-slim

# Use a closer mirror (change to your region if needed)
RUN echo "deb http://mirror.aarnet.edu.au/debian/ bookworm main" > /etc/apt/sources.list && \
    echo "deb http://mirror.aarnet.edu.au/debian/ bookworm-updates main" >> /etc/apt/sources.list

RUN apt-get update && apt-get install -y \
    cups \
    python3 \
    python3-pip \
    python3-venv \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/spool/lpd

# Add i386 architecture and install 32-bit libraries BEFORE installing Brother drivers
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y libc6:i386 && \
    rm -rf /var/lib/apt/lists/*

# Now install Brother drivers
RUN wget https://download.brother.com/welcome/dlf100434/hl3150cdncupswrapper-1.1.4-0.i386.deb && \
    wget https://download.brother.com/welcome/dlf100432/hl3150cdnlpr-1.1.2-1.i386.deb && \
    dpkg -i hl3150cdnlpr-1.1.2-1.i386.deb && \
    dpkg -i hl3150cdncupswrapper-1.1.4-0.i386.deb && \
    rm hl3150cdncupswrapper-1.1.4-0.i386.deb hl3150cdnlpr-1.1.2-1.i386.deb

# Set up venv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install paho-mqtt

# Copy CUPS configs with printer setup
COPY cupsd.conf /etc/cups/cupsd.conf
COPY printers.conf /etc/cups/printers.conf
COPY ppd/ /etc/cups/ppd/

# Entrypoint to configure CUPS on startup
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 631

ENTRYPOINT ["/entrypoint.sh"]