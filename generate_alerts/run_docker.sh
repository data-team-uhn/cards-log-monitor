#!/bin/bash

ARGS=$@

docker run \
	--rm \
	${DOCKER_NETWORK:+--network $DOCKER_NETWORK} \
	-e ERROR_LOG_TEXT \
	-e MONITORED_CONTAINER_PRETTY_NAME \
	-e SLACK_WEBHOOK_URL \
	-e LOKI_HOST \
	-e TZ=$(cat /etc/timezone) \
	-v $(realpath last_error_free_checkpoint.txt):/last_error_free_checkpoint.txt \
	-it \
	ghcr.io/data-team-uhn/cards-log-monitor $ARGS
