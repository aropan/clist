FROM php:8-fpm

# Use the default production configuration
RUN mv "$PHP_INI_DIR/php.ini-production" "$PHP_INI_DIR/php.ini"

RUN apt update -y
RUN docker-php-ext-install iconv
RUN apt install -y libicu-dev && docker-php-ext-install intl
RUN apt install -y libpq-dev && docker-php-ext-configure pgsql -with-pgsql=/usr/local/pgsql && docker-php-ext-install pgsql

# Freeze time() for offline schedule parser fixture replay (tests/run.php)
RUN apt install -y faketime

# Curl
RUN apt install -y wget
COPY src/scripts/install_curl.bash src/scripts/install_curl.sums ./
RUN ./install_curl.bash
RUN rm install_curl.bash install_curl.sums

# Configure python
COPY legacy/requirements.txt .
RUN apt install -y python3 python3-pip python3-venv && \
    python3 -m venv /venv/legacy && \
    /venv/legacy/bin/pip install -U pip && \
    /venv/legacy/bin/pip install -r requirements.txt
ENV PATH="/venv/legacy/bin/:$PATH"

# Configure cron
RUN apt install -y cron
COPY legacy/cron /etc/cron.d/clist
RUN echo "PATH=$PATH" | cat - /etc/cron.d/clist > temp && mv temp /etc/cron.d/clist
RUN chmod 0644 /etc/cron.d/clist
RUN crontab /etc/cron.d/clist

ENV APPDIR=/usr/src/legacy
WORKDIR $APPDIR

CMD bash -c "cron && php-fpm"
