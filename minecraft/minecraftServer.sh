#!/bin/sh
sleep 10
if tmux has-session -t minecraft > /dev/null 2>&1; then
	echo "minecraft server already running"
else
	echo "Starting minecraft session"
	tmux new-session -d -s minecraft
	sleep 5
	tmux send-keys -t minecraft "cd /home/spencer/Desktop//MineCraft\ Server/" ENTER
	tmux send-keys -t minecraft "/home/spencer/Desktop//MineCraft\ Server/start.sh" ENTER
fi

sleep
