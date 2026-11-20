# Standard library only: no pip installs.
FROM python:3.13-alpine
WORKDIR /app
COPY app.py index.html stations.json network.json complexes.json favicon.svg apple-touch-icon.png icon-192.png icon-512.png manifest.webmanifest ./
USER 65534:65534
EXPOSE 8400
CMD ["python", "-u", "app.py"]
