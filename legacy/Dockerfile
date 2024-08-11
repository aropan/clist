FROM php:8-fpm

# Use the default production configuration
RUN mv "$PHP_INI_DIR/php.ini-production" "$PHP_INI_DIR/php.ini"

RUN apt update -y
RUN docker-php-ext-install iconv
RUN apt install -y libicu-dev && docker-php-ext-install intl
RUN apt install -y libpq-dev && docker-php-ext-configure pgsql -with-pgsql=/usr/local/pgsql && docker-php-ext-install pgsql

# Curl
ENV CURL_VERSION=8.9.1
RUN curl -L https://github.com/stunnel/static-curl/releases/download/${CURL_VERSION}/curl-linux-aarch64-${CURL_VERSION}.tar.xz --output /tmp/curl.tar.xz && \
    tar -xvf /tmp/curl.tar.xz -C /tmp && \
    sha256sum /tmp/curl | grep -q "eff254056270ded081d677f2f04847817a1be692283bd5b37fbc379bed8d5461" && \
    mv /tmp/curl /usr/local/bin/curl && \
    rm /tmp/curl.tar.xz

# Configure python
COPY requirements.txt .
RUN apt install -y python3 python3-pip python3-venv && \
    python3 -m venv /venv/legacy && \
    /venv/legacy/bin/pip install -U pip && \
    /venv/legacy/bin/pip install -r requirements.txt
ENV PATH="/venv/legacy/bin/:$PATH"

# Configure cron
RUN apt install -y cron
COPY cron /etc/cron.d/clist
RUN echo "PATH=$PATH" | cat - /etc/cron.d/clist > temp && mv temp /etc/cron.d/clist
RUN chmod 0644 /etc/cron.d/clist
RUN crontab /etc/cron.d/clist

# Sentry CLI
RUN curl -sL https://sentry.io/get-cli/ | SENTRY_CLI_VERSION="2.20.7" sh

ENV APPDIR=/usr/src/legacy
WORKDIR $APPDIR

CMD bash -c "cron && php-fpm"
