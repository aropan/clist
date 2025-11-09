#!/usr/bin/env python3


import logging
import random
import re
from collections import defaultdict
from os import getenv

import requests

from utils.parsed_table import ParsedTable


class Proxy(dict):

    def __init__(self, **kwargs):
        proxy = kwargs.pop('proxy')
        super().__init__(**kwargs)
        self['addr'], self['port'] = proxy.split(':')

    def __getattr__(self, key):
        return self[key]


class ProxyList:

    @staticmethod
    def is_proxy(proxy):
        return re.match(r'^\d+\.\d+\.\d+\.\d+:\d+$', proxy)

    @staticmethod
    def _get_proxy_from_html():
        urls = [
            'https://free-proxy-list.net',
            'https://sslproxies.org',
            # 'https://www.proxynova.com/proxy-server-list/',
            # 'https://proxydb.net/?protocol=https',
            # 'https://spys.one/en/free-proxy-list/',
        ]
        for url in urls:
            source = url.split('/')[2]
            response = requests.get(url)
            header_mapping = {'IP Address': 'ip'}
            table = ParsedTable(response.content, header_mapping=header_mapping)
            table = [{k.lower(): v.value for k, v in row.items()} for row in table]
            for row in table:
                is_https = None
                if 'https' in row:
                    is_https = row['https'].lower() in {'true', '1', 't', 'y', 'yes'}
                elif 'type' in row:
                    is_https = row['type'].lower() in {'https'}
                else:
                    raise ValueError(f'Unknown proxy type in {row}')
                if is_https:
                    yield Proxy(proxy=f'{row["ip"]}:{row["port"]}', source=source)

    @staticmethod
    def _get_proxy_from_json():
        urls = [
            ('https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=https&proxy_format=ipport&format=json&limit=500', 'proxies'),  # noqa
            ('https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=http,https', 'data'),
        ]
        for url, key in urls:
            source = url.split('/')[2]
            try:
                response = requests.get(url)
                table = response.json()
                table = table[key]
            except Exception as e:
                logging.warning(f'Failed to get proxies from {url}: {e}')
                continue
            for row in table:
                yield Proxy(proxy=f'{row["ip"]}:{row["port"]}', source=source)

    @staticmethod
    def _get_proxy_from_text():
        urls = [
            'https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt',
            'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
        ]
        for url in urls:
            source = '/'.join(url.split('/')[3:5])
            response = requests.get(url)
            for line in response.text.strip().split('\n'):
                if ProxyList.is_proxy(line.strip()):
                    yield Proxy(proxy=line.strip(), source=source)

    @staticmethod
    def get():
        proxy = getenv('REQUESTER_PROXY')
        if proxy and ':' in proxy:
            return [Proxy(proxy=proxy, source='env')]

        logging.info('Getting proxy list...')
        proxies = []
        proxies.extend(ProxyList._get_proxy_from_html())
        proxies.extend(ProxyList._get_proxy_from_json())
        proxies.extend(ProxyList._get_proxy_from_text())
        random.shuffle(proxies)

        sources = defaultdict(int)
        skipped = defaultdict(int)
        ret = []
        for proxy in proxies:
            if sources[proxy.source] < 50:
                sources[proxy.source] += 1
                ret.append(proxy)
            else:
                skipped[proxy.source] += 1
        logging.info(f'Got {len(proxies)} proxies: {sources}, skipped: {skipped}')
        return ret
