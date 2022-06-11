FROM python:3.10

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN pip install "uwsgi==2.0.20"
RUN pip install "supervisor==4.2.4"
RUN pip install "daphne==3.0.2"

RUN apt update -y

# Decode raw protobuf message while parse some resources
RUN apt install -y protobuf-compiler

RUN apt install -y cron
# Copy hello-cron file to the cron.d directory
COPY cron /etc/cron.d/clist
# Give execution rights on the cron job
RUN chmod 0644 /etc/cron.d/clist
# Apply cron job
RUN crontab /etc/cron.d/clist

ENV APPDIR=/usr/src/clist
# COPY . .
WORKDIR $APPDIR

COPY supervisord.conf /etc/supervisord.conf
CMD supervisord -c /etc/supervisord.conf
