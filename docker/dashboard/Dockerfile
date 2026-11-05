# Ubuntu 26.04 so journalctl matches the host's systemd (259) and can read its journal files.
# python3-cryptography: AES for the Kasa plugs' local KLAP protocol (lights card).
FROM ubuntu:26.04
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-cryptography systemd ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app.py index.html favicon.svg favicon.ico apple-touch-icon.png icon-192.png icon-512.png manifest.webmanifest ./
USER 65534:65534
EXPOSE 7576
CMD ["python3", "-u", "app.py"]
