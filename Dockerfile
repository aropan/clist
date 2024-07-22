FROM python:3.10.11 as base

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt update -y
RUN apt install --reinstall build-essential -y

# Decode raw protobuf message while parse some resources
RUN apt install -y protobuf-compiler

# Setup tesseract
RUN apt install -y tesseract-ocr tesseract-ocr-eng
RUN find / -name "tessdata" | grep tesseract | head -n 1 | xargs -I {} wget --quiet -O "{}/eng.traineddata" https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/eng.traineddata

# Django bash completion
RUN apt install -y bash-completion
RUN wget -O /etc/bash_completion.d/django_bash_completion.sh https://raw.github.com/django/django/master/extras/django_bash_completion
RUN echo "if [ -f /etc/bash_completion ]; then . /etc/bash_completion; fi" >> ~/.bashrc

# Useful packages
RUN apt install -y lsof htop vim

# Setup python requirements
RUN pip install "pip==23.2"
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache pip install -r requirements.txt

# Sentry CLI
RUN curl -sL https://sentry.io/get-cli/ | SENTRY_CLI_VERSION="2.20.7" sh

# Curl
RUN wget https://github.com/stunnel/static-curl/releases/download/8.6.0-1/curl-linux-aarch64-8.6.0.tar.xz -O /tmp/curl.tar.xz && \
    tar -xvf /tmp/curl.tar.xz -C /tmp && \
    sha256sum /tmp/curl | grep -q "b42ad13ff77ea6baaacc2d560ace242ae449f8429ec47aa61ce3edd99879973c" && \
    mv /tmp/curl /usr/local/bin/curl && \
    rm /tmp/curl.tar.xz

RUN apt update --fix-missing

ENV APPDIR=/usr/src/clist
WORKDIR $APPDIR


FROM base as dev
ENV DJANGO_ENV_FILE .env.dev
RUN apt install -y redis-server
CMD sh -c 'redis-server --daemonize yes; scripts/watchdog.bash "python manage.py rqworker" "*.py"; python manage.py runserver 0.0.0.0:10042'

COPY config/ipython_config.py .
RUN ipython profile create
RUN cat ipython_config.py >> ~/.ipython/profile_default/ipython_config.py
RUN rm ipython_config.py


FROM base as prod
ENV DJANGO_ENV_FILE .env.prod
RUN apt install -y cron redis-server

COPY src/ $APPDIR/
COPY legacy/api/ $APPDIR/legacy/api/

COPY config/cron /etc/cron.d/clist
RUN chmod 0644 /etc/cron.d/clist
RUN crontab /etc/cron.d/clist

COPY config/uwsgi.ini $APPDIR/

RUN mkdir /run/daphne

COPY config/redis.conf /etc/redis/redis.conf

COPY config/supervisord.conf /etc/supervisord.conf
CMD supervisord -c /etc/supervisord.conf


FROM ubuntu:latest as loggly
RUN apt-get update && apt-get install -y rsyslog
RUN sed -i '/imklog/s/^/# /g' /etc/rsyslog.conf
COPY config/loggly/entrypoint.sh /entrypoint.sh
COPY config/loggly/60-loggly.conf /etc/rsyslog.d/60-loggly.conf
ENTRYPOINT /entrypoint.sh


FROM nginx:alpine as nginx
RUN apk add --no-cache logrotate
COPY config/nginx/logrotate.d/nginx /etc/logrotate.d/nginx
RUN chmod 0644 /etc/logrotate.d/nginx
