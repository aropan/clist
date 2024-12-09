#!/usr/bin/env python3


import logging
import random
import re
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
        ]
        for url in urls:
            source = url.split('//')[1].split('/')[0]
            response = requests.get(url)
            table = ParsedTable(response.content)
            table = [{k.lower(): v.value for k, v in row.items()} for row in table]
            for row in table:
                if row['https'].lower() in {'true', '1', 't', 'y', 'yes'}:
                    yield Proxy(proxy=f'{row["ip address"]}:{row["port"]}', source=source)

    @staticmethod
    def _get_proxy_from_json():
        urls = [
            ('https://proxylist.geonode.com/api/proxy-list?protocols=http%2Chttps&limit=500&page=1&sort_by=lastChecked&sort_type=desc&speed=medium', 'data'),  # noqa
            ('https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=http&proxy_format=ipport&format=json&timeout=500', 'proxies'),  # noqa
        ]
        for url, key in urls:
            source = url.split('//')[1].split('/')[0]
            response = requests.get(url)
            table = response.json()
            table = table[key]

            for row in table:
                yield Proxy(proxy=f'{row["ip"]}:{row["port"]}', source=source)

    @staticmethod
    def get():
        proxy = getenv('REQUESTER_PROXY')
        if proxy and ':' in proxy:
            return [Proxy(proxy=proxy, source='env')]

        ret = []
        logging.info('Getting proxy list...')

        code = getenv('HIDEME_PROXYLIST_CODE')
        if code:
            page = requests.get(f'https://proxylist.justapi.info/api/proxylist.txt?type=s&out=plain&code={code}')
            for proxy in page.text.splitlines():
                if ProxyList.is_proxy(proxy):
                    ret.append(Proxy(proxy=proxy, source='hidemyna.me'))

        # ret.extend(ProxyList._get_proxy_from_html())
        ret.extend(ProxyList._get_proxy_from_json())

        random.shuffle(ret)

        sources = {}
        for proxy in ret:
            sources[proxy.source] = sources.get(proxy.source, 0) + 1
        logging.info(f'Got {len(ret)} proxies: {sources}')

        return ret
