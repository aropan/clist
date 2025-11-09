FROM python:3.10.11 AS base

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
COPY --from=ghcr.io/astral-sh/uv:0.5.3 /uv /uvx /bin/
ENV UV_SYSTEM_PYTHON=1
ENV UV_LINK_MODE=copy
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv uv pip install -r requirements.txt

# Sentry CLI
RUN curl -sL https://sentry.io/get-cli/ | SENTRY_CLI_VERSION="2.20.7" sh

# Curl
RUN wget https://github.com/stunnel/static-curl/releases/download/8.16.0/curl-linux-aarch64-glibc-8.16.0.tar.xz -O /tmp/curl.tar.xz && \
    tar -xvf /tmp/curl.tar.xz -C /tmp && \
    sha256sum /tmp/curl | grep -q "abb2f02bcdaf25515118d1517bef3e9339d65dc21f13dc9503eecf2fa1843efc" && \
    mv /tmp/curl /usr/local/bin/curl && \
    rm /tmp/curl.tar.xz

# psql
RUN apt update --fix-missing && apt install -y postgresql-client

ENV APPDIR=/usr/src/clist
WORKDIR $APPDIR


FROM base AS dev
ENV DJANGO_ENV_FILE .env.dev
RUN apt install -y redis-server
CMD sh -c 'redis-server --daemonize yes; scripts/watchdog.bash "python manage.py rqworker system default parse_statistics parse_accounts" "**/*.py"; python manage.py runserver 0.0.0.0:10042'

COPY config/ipython_config.py .
RUN ipython profile create
RUN cat ipython_config.py >> ~/.ipython/profile_default/ipython_config.py
RUN rm ipython_config.py


FROM base AS prod
ENV DJANGO_ENV_FILE .env.prod
RUN apt install -y cron redis-server logrotate

COPY src/ $APPDIR/

COPY config/cron /etc/cron.d/clist
RUN chmod 0644 /etc/cron.d/clist
RUN crontab /etc/cron.d/clist

COPY config/uwsgi.ini $APPDIR/

RUN mkdir /run/daphne

COPY config/redis.conf /etc/redis/redis.conf

COPY config/supervisord.conf /etc/supervisord.conf

COPY config/logrotate.conf /etc/logrotate.d/clist
RUN chmod 0644 /etc/logrotate.d/clist

CMD supervisord -c /etc/supervisord.conf


FROM nginx:stable-alpine AS nginx
# logrotate
RUN apk add --no-cache logrotate
COPY config/nginx/logrotate.d/nginx /etc/logrotate.d/nginx
RUN chmod 0644 /etc/logrotate.d/nginx
# cron
RUN apk add --no-cache logrotate dcron
COPY config/nginx/cron /etc/cron.d/nginx
RUN chmod 0644 /etc/cron.d/nginx
RUN crontab /etc/cron.d/nginx

CMD crond && nginx -g "daemon off;"


FROM postgres:14.3-alpine AS postgres
# pg_repack
RUN apk add --no-cache --virtual .build-deps \
    gcc \
    g++ \
    make \
    musl-dev \
    postgresql-dev \
    git \
    lz4-dev \
    zlib-dev \
    bash \
    util-linux \
    gawk
RUN cd /tmp \
    && git clone --depth 1 --branch ver_1.5.1 https://github.com/reorg/pg_repack.git \
    && cd pg_repack \
    && make \
    && make install \
    && apk del .build-deps \
    && rm -rf /tmp/pg_repack
# numfmt
RUN apk add --no-cache coreutils
# cron
RUN apk add --no-cache dcron
COPY config/postgres/cron /etc/cron.d/postgres
RUN chmod 0644 /etc/cron.d/postgres
RUN crontab /etc/cron.d/postgres
# supervisord
RUN apk add --no-cache supervisor
COPY config/postgres/supervisord.conf /etc/supervisord.conf
# postgresql.conf
RUN mkdir -p /usr/src/clist/config/postgres
COPY config/postgres/postgresql.conf /usr/src/clist/config/postgres/postgresql.conf
RUN chown -R postgres:postgres /usr/src/clist/config/postgres
RUN chmod 644 /usr/src/clist/config/postgres/postgresql.conf

CMD supervisord -c /etc/supervisord.conf
