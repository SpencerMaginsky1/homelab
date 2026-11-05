# Ubuntu 26.04 so journalctl matches the host's systemd (259) and can read its journal files.
FROM ubuntu:26.04
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 systemd ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app.py index.html favicon.svg favicon.ico apple-touch-icon.png ./
USER 65534:65534
EXPOSE 7576
CMD ["python3", "-u", "app.py"]
