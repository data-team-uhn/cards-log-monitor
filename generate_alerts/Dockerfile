FROM alpine:3.17

RUN apk update
RUN apk add \
	python3 \
	py3-requests \
	tzdata

RUN mkdir /generate_alerts
COPY generate_alerts.py /generate_alerts/generate_alerts.py
COPY init_error_free_checkpoint.py /generate_alerts/init_error_free_checkpoint.py
COPY count_exports.py /generate_alerts/count_exports.py

WORKDIR /generate_alerts
CMD python3
