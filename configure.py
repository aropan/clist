#!/usr/bin/env python3

import logging
import os
import random
import re
import string
import subprocess
import time


def random_string(length=40):
    return ''.join(random.choices(list(string.ascii_letters + string.digits), k=length))


def create_logger():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger


def enter_value(variable, old_value):
    if not old_value:
        logger.info(f'Generated new value for {variable} default')
        old_value = random_string()
    if old_value == '{empty}':
        old_value = ''
    value = input(f'Enter {variable} [default "{old_value}"]: ')
    if not value:
        value = old_value
    return value


def fill_template(target_file, accept_default=False, allow_empty=False):
    template_file = target_file + '.template'
    if os.path.exists(target_file):
        logger.info(f'File {target_file} already exists')
        return

    logger.info(f'Generating {target_file}...')

    generated = ''
    n_sep_skip = 0
    with open(template_file, 'r') as fo:
        for line in fo:
            line = line.rstrip()
            parts = re.split(r'\s*=\s*', line, maxsplit=1)
            if len(parts) < 2:
                generated += f'{line}\n'
                continue

            entry = re.search(r'\s*=\s*', line)
            sep = entry.group(0)

            variable, old_value = parts
            entry = re.search('''^['"]''', old_value)
            quote = entry.group(0) if entry else ''
            if old_value.endswith('random-string'):
                old_value = ''
            if old_value and ' ' in sep:
                n_sep_skip += 1
                generated += f'{line}\n'
                continue
            if accept_default and (allow_empty or old_value):
                value = old_value
                logger.info(f'Accept default value "{old_value}" for "{variable}"')
            else:
                value = enter_value(variable, old_value)
            generated += f'{variable}{sep}{quote}{value}{quote}\n'

    with open(target_file, 'w') as fo:
        fo.write(generated)

    if n_sep_skip:
        logger.warning(f'Please fill other field in {target_file} if needed')


def run_command(cmd):
    cmd = cmd.replace('\n', ' ')
    not_sensitive_data = re.sub('"[^"]*"', '***', cmd)
    logger.info(f'Run command = {not_sensitive_data}')
    subprocess.run(cmd, shell=True, check=True)


def create_volumes():
    with open('docker-compose.yml', 'r') as fo:
        content = fo.read()
    folders = re.findall(r'^\s*device:\s*(.*)', content, re.MULTILINE)
    for folder in folders:
        if not os.path.exists(folder):
            logger.info(f'Creating volume {folder}')
            os.makedirs(folder)


def main():
    fill_template('.env.db')
    fill_template('.env.netdata', accept_default=True, allow_empty=True)
    fill_template('.env.sentry', accept_default=True, allow_empty=True)
    fill_template('src/.env.dev', accept_default=True)
    fill_template('src/.env.prod', accept_default=True)
    fill_template('src/pyclist/conf.py')
    create_volumes()
    run_command('docker compose build dev')
    run_command('docker compose up --build --detach db')
    logger.info('Waiting 30 seconds for database to start')
    time.sleep(30)
    run_command('docker compose run dev ./manage.py migrate contenttypes')
    run_command('docker compose run dev ./manage.py migrate auth')
    run_command('docker compose run dev ./manage.py migrate')

    username = enter_value('username', os.getlogin())
    password = enter_value('password', random_string(10))
    email = enter_value('email', 'admin@localhost')
    run_command(f'''
        docker compose run dev ./manage.py createadmin
        --username "{username}"
        --password "{password}"
        --email "{email}"
        --noinput
    ''')


if __name__ == '__main__':
    logger = create_logger()
    main()
