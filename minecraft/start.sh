#!/bin/sh
# 6 GB heap (was 8 GB; backup in start.sh.bak-8G). PreTouch claims the RAM at startup.
java -Xms6G -Xmx6G -XX:+UseG1GC -XX:+AlwaysPreTouch -jar server.jar nogui
