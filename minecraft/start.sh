#!/bin/sh
# 4 GB heap (was 6 GB, originally 8 GB; backups in start.sh.bak-6G / start.sh.bak-8G). PreTouch claims the RAM at startup.
java -Xms4G -Xmx4G -XX:+UseG1GC -XX:+AlwaysPreTouch -jar server.jar nogui
