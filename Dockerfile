FROM python:3.14.7-trixie@sha256:20f4b272cb5d0f462c84645f8127d82e6fcfdc4006f4dd7f8859a5be4d5ef7a5 AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt update -y && apt upgrade -y
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

# Setup Python dependencies
COPY --from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /uvx /bin/
ENV UV_PROJECT_ENVIRONMENT=/usr/local
ENV UV_LINK_MODE=copy
COPY pyproject.toml uv.lock .
RUN --mount=type=cache,id=clist-uv-py314-trixie,target=/root/.cache/uv \
    uv sync --locked --no-install-project --inexact --compile-bytecode
COPY src/scripts/patch_python_dependencies.py ./
RUN python patch_python_dependencies.py && rm patch_python_dependencies.py

# Curl
COPY src/scripts/install_curl.bash src/scripts/install_curl.sums ./
RUN ./install_curl.bash
RUN rm install_curl.bash install_curl.sums

# psql
RUN apt update --fix-missing && apt install -y postgresql-client

ENV APPDIR=/usr/src/clist
WORKDIR $APPDIR


FROM base AS dev
ENV DJANGO_ENV_FILE=.env.dev
ENV PYTHONDONTWRITEBYTECODE=""
ENV PYTHONPYCACHEPREFIX=/tmp/clist-pycache
RUN apt install -y redis-server
CMD ["sh", "-c", "bash scripts/wait-for-postgres.bash; redis-server --daemonize yes --save '' --dir /tmp; scripts/watchdog.bash 'python manage.py rqworker system default parse_statistics parse_accounts' '**/*.py'; exec python manage.py runserver 0.0.0.0:10042"]

COPY config/ipython_config.py .
RUN ipython profile create
RUN cat ipython_config.py >> ~/.ipython/profile_default/ipython_config.py
RUN rm ipython_config.py


FROM base AS prod
ENV DJANGO_ENV_FILE=.env.prod
ENV SUPERVISOR_CRON_AUTOSTART=true
ENV SUPERVISOR_RQ_AUTOSTART=true
RUN apt install -y cron redis-server logrotate rsync

COPY src/ $APPDIR/
RUN mkdir -p $APPDIR/logs/rqworker
RUN chmod +x $APPDIR/scripts/start-production.bash
RUN python -m compileall -q -j 0 $APPDIR

COPY config/cron /etc/cron.d/clist
RUN chmod 0644 /etc/cron.d/clist
RUN crontab /etc/cron.d/clist

COPY config/uwsgi.ini $APPDIR/

RUN mkdir /run/daphne

COPY config/redis.conf /etc/redis/redis.conf

COPY config/supervisord.conf /etc/supervisord.conf

COPY config/logrotate.conf /etc/logrotate.d/clist
RUN chmod 0644 /etc/logrotate.d/clist

CMD ["scripts/start-production.bash"]


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


FROM postgres:18-alpine3.24 AS postgres
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
    && git clone --depth 1 --branch ver_1.5.3 https://github.com/reorg/pg_repack.git \
    && cd pg_repack \
    && make with_llvm=no \
    && make with_llvm=no install \
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

CMD ["supervisord", "-c", "/etc/supervisord.conf"]


FROM postgres AS backup
RUN apk add --no-cache python3 py3-pip \
    && python3 -m venv /opt/clist-backup \
    && /opt/clist-backup/bin/pip install --no-cache-dir rich==15.0.0
COPY --chmod=755 src/scripts/backup_postgres.py /usr/local/bin/backup-postgres

ENTRYPOINT ["/opt/clist-backup/bin/python", "/usr/local/bin/backup-postgres"]
CMD []
