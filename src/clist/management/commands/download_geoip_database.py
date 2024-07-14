#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import shutil
import tarfile
import tempfile
from logging import getLogger

import requests
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Downloadn GeoIP2 database'

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.logger = getLogger('clist.download_geoip2_database')

    def handle(self, *args, **options):
        edition_id = 'GeoLite2-Country'
        download_url = f'https://download.maxmind.com/app/geoip_download?edition_id={edition_id}&license_key={settings.GEOIP_LICENSE_KEY}&suffix=tar.gz'  # noqa E501
        response = requests.get(download_url, stream=True)
        with tempfile.TemporaryDirectory() as temp_dir:
            self.logger.info(f'temp_dir = {temp_dir}')
            tar_file_path = f'{temp_dir}/{edition_id}.tar.gz'
            with open(tar_file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=4096):
                    f.write(chunk)
            self.logger.info(f'downloaded file = {tar_file_path}')

            extract_dir = f'{temp_dir}/{edition_id}'
            with tarfile.open(tar_file_path) as tar:
                tar.extractall(path=extract_dir)
            self.logger.info(f'extracted to {extract_dir}')

            geoip_path_basename = os.path.basename(settings.GEOIP_PATH)
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    self.logger.info(f'downloaded file = {file_path}')
                    if file == geoip_path_basename:
                        shutil.move(file_path, settings.GEOIP_PATH)
                        self.logger.info(f'moved file = {settings.GEOIP_PATH}')
