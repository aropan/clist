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

# vim
RUN apt install -y vim

# Setup python requirements
RUN pip install "pip==22.1.2"
COPY requirements.txt .
RUN pip install -r requirements.txt

ENV APPDIR=/usr/src/clist
WORKDIR $APPDIR


FROM base as dev
ENV DJANGO_ENV_FILE .env.dev
CMD python manage.py runserver 0.0.0.0:10042


FROM base as prod
ENV DJANGO_ENV_FILE .env.prod
RUN apt install -y cron
# Copy hello-cron file to the cron.d directory
COPY cron /etc/cron.d/clist
# Give execution rights on the cron job
RUN chmod 0644 /etc/cron.d/clist
# Apply cron job
RUN crontab /etc/cron.d/clist

RUN pip install "uwsgi==2.0.20" "supervisor==4.2.4" "daphne==3.0.2"
COPY . $APPDIR
COPY supervisord.conf /etc/supervisord.conf
CMD supervisord -c /etc/supervisord.conf
