FROM python:3.10 as base

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt update -y

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
RUN pip install "pip==22.1.2"
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache pip install -r requirements.txt

# Sentry CLI
RUN curl -sL https://sentry.io/get-cli/ | SENTRY_CLI_VERSION="2.12.0" sh

RUN apt update --fix-missing

ENV APPDIR=/usr/src/clist
WORKDIR $APPDIR


FROM base as dev
ENV DJANGO_ENV_FILE .env.dev
RUN apt install -y redis-server
CMD redis-server --daemonize yes; python manage.py runserver 0.0.0.0:10042

COPY ipython_config.py .
RUN ipython profile create
RUN cat ipython_config.py >> ~/.ipython/profile_default/ipython_config.py
RUN rm ipython_config.py


FROM base as prod
ENV DJANGO_ENV_FILE .env.prod
RUN apt install -y cron redis-server

COPY ./src/ $APPDIR/
COPY ./legacy/api/ $APPDIR/legacy/api/

COPY cron /etc/cron.d/clist
RUN chmod 0644 /etc/cron.d/clist
RUN crontab /etc/cron.d/clist

COPY ./uwsgi.ini $APPDIR/

RUN mkdir /run/daphne

COPY ./redis.conf /etc/redis/redis.conf

COPY supervisord.conf /etc/supervisord.conf
CMD supervisord -c /etc/supervisord.conf
