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
    def get():
        ret = []
        logging.info('Getting proxy list...')

        code = getenv('HIDEME_PROXYLIST_CODE')
        if code:
            page = requests.get(f'https://proxylist.justapi.info/api/proxylist.txt?type=s&out=plain&code={code}')
            for proxy in page.text.splitlines():
                if ProxyList.is_proxy(proxy):
                    ret.append(Proxy(proxy=proxy, source='hidemyna.me'))

        urls = [
            'https://free-proxy-list.net',
            'https://sslproxies.org',
        ]
        for url in urls:
            source = url.split('//')[1].split('/')[0]
            page = requests.get(url)
            table = ParsedTable(page.content)
            for row in table:
                row = {k.lower(): v.value for k, v in row.items()}
                if row['https'].lower() in {'true', '1', 't', 'y', 'yes'}:
                    ret.append(Proxy(proxy=f'{row["ip address"]}:{row["port"]}', source=source))

        random.shuffle(ret)

        sources = defaultdict(int)
        for proxy in ret:
            sources[proxy.source] += 1
        logging.info(f'Got {len(ret)} proxies: {sources}')

        return ret
