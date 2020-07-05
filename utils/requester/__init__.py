#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-


import traceback
import re
import urllib.request
import urllib.parse
import urllib.error
import logging
import mimetypes
import random
import string
import html
import requests
from os import path, makedirs, listdir, remove, stat, environ
from os.path import isdir, getctime
from json import loads, dumps, load
from http.cookiejar import MozillaCookieJar
from sys import stderr
from gzip import GzipFile
from hashlib import md5
from io import BytesIO
from time import sleep
from datetime import datetime
from string import ascii_letters, digits
from random import choice, gauss
from distutils.util import strtobool

import chardet


logging.getLogger('chardet.charsetprober').setLevel(logging.INFO)


class FileWithProxiesNotFound(Exception):
    pass


class ListProxiesEmpty(Exception):
    pass


class FailOnGetResponse(Exception):
    pass


class NoVerifyWord(Exception):
    pass


class SlowlyProxy(Exception):
    pass


class proxer():
    LIMIT_FAIL = 3
    DIVIDER = 3
    LIMIT_TIME = 2.5

    def load_data(self):
        try:
            with open(self.file_name, "r") as fo:
                self.data = load(fo)
        except (IOError, ValueError):
            self.data = {}

    def save_data(self):
        if (
            self.proxy and
            self.proxy["_fail"] >= self.LIMIT_FAIL
            or
            self.is_slow_proxy()
        ):
            del self.data[self.proxy_key]
        j = dumps(
            self.data,
            indent=4,
            sort_keys=True,
            ensure_ascii=False
        )
        with open(self.file_name, "w") as fo:
            fo.write(j)

    def is_slow_proxy(self):
        if self.proxy and self.proxy.get("_count", 0) > 9:
            return self.time_response() > self.LIMIT_TIME

    @staticmethod
    def get_timestamp():
        return int(datetime.utcnow().strftime("%s"))

    @staticmethod
    def get_score(proxy):
        return (proxy["_success"] - proxer.DIVIDER ** proxy["_fail"], -proxy["_timestamp"])

    def add(self, proxy):
        value = self.data.setdefault(proxy, {})
        value["addr"], value["port"] = proxy.split(":")
        value.setdefault("_success", 0)
        value.setdefault("_fail", 0)
        value.setdefault("_timestamp", self.get_timestamp())

    def get(self):
        self.proxy = None
        for k, v in self.data.items():
            if self.proxy is None or self.get_score(v) > self.get_score(self.proxy):
                self.proxy = v
                self.proxy_key = k
        if not self.proxy:
            raise ListProxiesEmpty()
        self.proxy["_timestamp"] = self.get_timestamp()
        return "%(addr)s:%(port)s" % self.proxy

    def ok(self, time_response=None):
        if self.proxy:
            self.proxy["_success"] += 1
            for i in range(self.LIMIT_FAIL):
                if self.proxy["_fail"] <= i:
                    break
                if self.proxy["_success"] > 2 ** (2 ** (self.LIMIT_FAIL - i)) + 10:
                    self.proxy["_fail"] = i
                    break
            if time_response:
                self.proxy.setdefault("_count", 0)
                self.proxy.setdefault("_total_time", 0.)
                self.proxy["_count"] += 1
                self.proxy["_total_time"] += time_response.total_seconds() + time_response.microseconds / 1000000.
                if self.is_slow_proxy():
                    raise SlowlyProxy("%s, %.3f" % (self.proxy["addr"], self.time_response()))

    def fail(self):
        if self.proxy:
            self.proxy["_success"] //= self.DIVIDER
            self.proxy["_fail"] += 1

    def time_response(self):
        if self.proxy and self.proxy.get("_count", 0):
            return self.proxy["_total_time"] / self.proxy["_count"]

    def __init__(self, file_name):
        self.file_name = file_name + ".json"
        self.load_data()
        with open(file_name, "r") as fo:
            for line in fo:
                line = line.strip()
                if not line:
                    continue
                self.add(line)
        self.proxy = None
        open(file_name, "w").close()

    def __exit__(self, *err):
        self.close()


def encode_multipart(fields=None, files=None, boundary=None):
    """Encode multipart form data to upload files via POST.
    http://code.activestate.com/recipes/578668-encode-multipart-form-data-for-uploading-files-via/"""

    r"""Encode dict of form fields and dict of files as multipart/form-data.
    Return tuple of (body_string, headers_dict). Each value in files is a dict
    with required keys 'filename' and 'content', and optional 'mimetype' (if
    not specified, tries to guess mime type or uses 'application/octet-stream').

    >>> body, headers = encode_multipart({'FIELD': 'VALUE'},
    ...                                  {'FILE': {'filename': 'F.TXT', 'content': 'CONTENT'}},
    ...                                  boundary='BOUNDARY')
    >>> print('\n'.join(repr(l) for l in body.split('\r\n')))
    '--BOUNDARY'
    'Content-Disposition: form-data; name="FIELD"'
    ''
    'VALUE'
    '--BOUNDARY'
    'Content-Disposition: form-data; name="FILE"; filename="F.TXT"'
    'Content-Type: text/plain'
    ''
    'CONTENT'
    '--BOUNDARY--'
    ''
    >>> print(sorted(headers.items()))
    [('Content-Length', '193'), ('Content-Type', 'multipart/form-data; boundary=BOUNDARY')]
    >>> len(body)
    193
    """
    def escape_quote(s):
        return s.replace('"', '\\"')

    if boundary is None:
        boundary = ''.join(random.choice(string.digits + string.ascii_letters) for i in range(30))
    lines = []

    fields = fields or {}
    for name, value in fields.items():
        lines.extend((
            '--{0}'.format(boundary),
            'Content-Disposition: form-data; name="{0}"'.format(escape_quote(name)),
            '',
            str(value),
        ))

    files = files or {}
    for name, value in files.items():
        filename = value['filename']
        if 'mimetype' in value:
            mimetype = value['mimetype']
        else:
            mimetype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        lines.extend((
            '--{0}'.format(boundary),
            'Content-Disposition: form-data; name="{0}"; filename="{1}"'.format(
                    escape_quote(name), escape_quote(filename)),
            'Content-Type: {0}'.format(mimetype),
            '',
            value['content'],
        ))

    lines.extend((
        '--{0}--'.format(boundary),
        '',
    ))
    body = '\r\n'.join(lines)
    body = body.encode('utf8')

    headers = {
        'Content-Type': 'multipart/form-data; boundary={0}'.format(boundary),
        'Content-Length': len(body),
    }

    return body, headers


class requester():
    cache_timeout = 10940
    caching = True
    assert_on_fail = True
    time_out = 4
    debug_output = True
    dir_cache = path.dirname(path.realpath(__file__)) + "/cache/"
    cookie_filename = path.abspath(path.realpath(__file__)) + ".cookie"
    last_page = None
    last_url = None
    ref_url = None
    time_sleep = 1e-1
    limit_file_cache = 200
    counter_file_cache = 0
    verify_word = None

    def print(self, *objs, force=False):
        if self.debug_output or force:
            print(datetime.utcnow(), *objs, file=stderr)

    def __init__(self,
                 proxy=bool(strtobool(environ.get('REQUESTER_PROXY', '0'))),
                 cookie_filename=None,
                 caching=None,
                 user_agent=None,
                 headers=None,
                 file_name_with_proxies=path.join(path.dirname(__file__), 'proxies.txt')):
        self.opened = None
        if cookie_filename:
            self.cookie_filename = cookie_filename
        if caching is not None:
            self.caching = caching
        if headers:
            self.headers = headers
        else:
            self.headers = [
                ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'),
                ('Accept-Encoding', 'gzip, deflate'),
                ('Accept-Language', 'ru-ru,ru;q=0.8,en-us;q=0.5,en;q=0.3'),
                ('Connection', 'keep-alive'),
                (
                    'User-Agent',
                    'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:10.0.2) Gecko/20100101 Firefox/10.0.2'
                    if user_agent is None else user_agent
                )
            ]
        if self.cookie_filename:
            makedirs(path.dirname(self.cookie_filename), exist_ok=True)
            self.cookiejar = MozillaCookieJar(self.cookie_filename)
            if path.exists(self.cookie_filename):
                self.cookiejar.load()
        else:
            self.cookiejar = MozillaCookieJar()

        self.http_cookie_processor = urllib.request.HTTPCookieProcessor(self.cookiejar)
        self.opener = urllib.request.build_opener(self.http_cookie_processor)
        self.proxer = None
        if proxy:
            if proxy is True:
                if not file_name_with_proxies or not path.exists(file_name_with_proxies):
                    raise FileWithProxiesNotFound("ERROR: not found '%s' file" % file_name_with_proxies)
                self.proxer = proxer(file_name_with_proxies)
                proxy = self.proxer.get()
                self.print("[proxy]", proxy)
                time_response = self.proxer.time_response()
                if time_response:
                    self.print("[average time]", time_response)

            self.opener.add_handler(urllib.request.ProxyHandler({
                'http': proxy,
                'https': proxy,
            }))

        self._init_opener_headers = self.headers

    def get(
        self,
        url,
        post=None,
        caching=None,
        is_ref_url=True,
        md5_file_cache=None,
        time_out=None,
        headers=None,
        detect_charsets=False,
        content_type=None,
        files=None,
        return_url=False,
    ):
        prefix = "local-file:"
        if url.startswith(prefix):
            with open(url[len(prefix):], "r") as fo:
                page = fo.read().decode("utf8")
                self.last_page = page
            return page

        if not url.startswith('http') and self.last_url:
            url = urllib.parse.urljoin(self.last_url, url)
        if caching is None:
            caching = self.caching
        url = url.replace('&amp;', '&')
        url = url.replace(' ', '%20')

        makedirs(self.dir_cache, mode=0o777, exist_ok=True)

        files = files or isinstance(post, dict) and post.pop('files__', None)
        post_urlencoded = urllib.parse.urlencode(post).encode('utf-8') if post and isinstance(post, dict) else post

        try:
            file_cache = ''.join((
                self.dir_cache,
                md5((md5_file_cache or url + (post_urlencoded or "")).encode()).hexdigest(),
                ("/" + url[url.find("//") + 2:].split("?", 2)[0]).replace("/", "_"),
                ".html",
            ))
        except Exception:
            file_cache = None

        caching = file_cache and caching and self.cache_timeout > 0

        from_cache = caching
        if caching:
            if not path.isfile(file_cache):
                from_cache = False
            else:
                diff_time = datetime.now() - datetime.fromtimestamp(path.getctime(file_cache))
                from_cache = diff_time.seconds < self.cache_timeout
        self.print("[cache]" if from_cache else "", url, force=from_cache)
        self.error = None
        response = None
        last_url = None
        if from_cache:
            with open(file_cache, "r") as f:
                page = f.read().encode('utf8')
        else:
            if self.time_sleep:
                v_time_sleep = min(1, abs(gauss(0, 1)) * self.time_sleep)
                sleep(v_time_sleep)
            if not headers:
                headers = {}
            if self.ref_url and 'Referer' not in headers:
                headers.update({"Referer": self.ref_url})
            if not self.last_url or urllib.parse.urlparse(self.last_url).netloc != urllib.parse.urlparse(url).netloc:
                self.opener.addheaders = self._init_opener_headers
            if headers:
                h = dict(self.opener.addheaders)
                h.update(headers)
                self.opener.addheaders = list(h.items())

            if content_type == 'multipart/form-data' and post or files:
                post_urlencoded, multipart_headers = encode_multipart(fields=post, files=files)
                headers.update(multipart_headers)
            elif content_type:
                headers.update({"Content-type": content_type})

            try:
                if headers:
                    request = urllib.request.Request(url, headers=headers)
                else:
                    request = url

                time_start = datetime.utcnow()
                response = self.opener.open(
                    request,
                    post_urlencoded if post else None,
                    timeout=time_out or self.time_out,
                )
                last_url = response.geturl() if response else url
                if response.info().get("Content-Encoding", None) == "gzip":
                    buf = BytesIO(response.read())
                    page = GzipFile(fileobj=buf).read()
                else:
                    page = response.read()
                self.time_response = datetime.utcnow() - time_start
                if self.verify_word and self.verify_word not in page:
                    raise NoVerifyWord("No verify word '%s', size page = %d" % (self.verify_word, len(page)))
            except Exception as err:
                self.error = err
                if self.assert_on_fail:
                    if self.proxer:
                        self.proxer.fail()
                    raise FailOnGetResponse(err)
                else:
                    traceback.print_exc()
                return

            try:
                if file_cache and caching:
                    cookie_write = True
                    if response.info().get("Content-Type").startswith("application/json"):
                        page = dumps(loads(page), indent=4)
                        cookie_write = False
                    if response.info().get("Content-Type").startswith("image/"):
                        cookie_write = False
                    with open(file_cache, "w") as f:
                        f.write(page.decode('utf8'))
                        if cookie_write:
                            f.write("\n\n" + dumps(self.get_cookies(), indent=4))
            except Exception:
                traceback.print_exc()
                self.print("[cache] ERROR: write to", file_cache)

            if self.proxer:
                if not self.error:
                    self.proxer.ok(self.time_response)
                else:
                    self.proxer.fail()

        matches = re.findall(r'charset=["\']?(?P<charset>[^"\'\s\.>;]{3,}\b)', str(page), re.IGNORECASE)
        if matches:
            charsets = [c.lower() for c in matches]
            if len(charsets) > 1 and len(set(charsets)) > 1:
                self.print(f'[WARNING] set multi charset values: {charsets}')
            charset = charsets[-1].lower()
        else:
            charset = 'utf-8'

        if detect_charsets:
            try:
                charset_detect = chardet.detect(page)
                if charset_detect and charset_detect['confidence'] > 0.98:
                    charset = charset_detect['encoding']
            except Exception as e:
                self.print('exception on charset detect:', str(e))

        if charset in ('utf-8', 'utf8'):
            page = page.decode('utf-8', 'replace')
        elif charset in ('windows-1251', 'cp1251'):
            page = page.decode('cp1251', 'replace')
        else:
            page = page.decode(charset, 'replace')

        self.last_page = page
        if is_ref_url:
            self.ref_url = self.last_url
        self.file_cache_clear()
        self.response = response
        self.last_url = last_url
        return (page, last_url) if return_url else page

    @property
    def current_url(self):
        return self.last_url

    def head(self, url):
        return requests.head(url)

    def get_link_by_text(self, text, page=None):
        if page is None:
            page = self.last_page
        match = re.search(
            r"""
            <a[^>]*href="(?P<href>[^"]*)"[^>]*>\s*
                (?:</?[^a][^>]*>\s*)*
                %s
            """ % text.replace(" ", r"\s"),
            page,
            re.VERBOSE
        )
        if not match:
            return
        return match.group("href")

    def get_link_by_text_and_go_if_exist(self, text):
        url = self.get_link_by_text(text)
        if url:
            self.get(url)
        return self.last_page

    def form(self, page=None, action='', limit=1, fid=None, selectors=(), enctype=False):
        if page is None:
            page = self.last_page
        selectors = list(selectors)
        selectors += ['''method=["'](?P<method>post|get)"''']
        if action is not None:
            selectors += [f'''action=["'](?P<url>[^"']*{action}[^"']*)["']''']
            limit += 1
        if fid is not None:
            selectors.append(f'id="{fid}"')
            limit += 1
        if enctype:
            selectors.append('enctype="(?P<enctype>[^"]*)"')
            limit += 1

        selector = '|[^>]*'.join(selectors)
        regex = f'''
            <form([^>]*{selector}){{{limit}}}[^>]*>
            .*?
            </form>
        '''
        match = re.search(regex, page, re.DOTALL | re.VERBOSE | re.IGNORECASE)
        if not match:
            return None
        page = match.group()
        result = match.groupdict()
        post = {}
        fields = re.finditer(
            r'''
            (?:
                type=["'](?P<type>[^"']*)["']\s*|
                value=["'](?P<value>[^"']*)["']\s*|
                name=["'](?P<name>[^"']*)["']\s*|
                [-a-z]+=["'][^"']*["']\s*|
                (?P<checked>checked)\s*
            ){2,}''',
            page,
            re.VERBOSE | re.IGNORECASE
        )

        unchecked = []
        for field in fields:
            field = field.groupdict()
            if field["name"] is None or field["value"] is None:
                continue
            if field["type"] == "checkbox" and field["checked"] is None:
                unchecked.append(field)
            else:
                post[field['name']] = html.unescape(field['value'])

        fields = re.finditer(r'''<select[^>]*name="(?P<name>[^"]*)"[^>]*>''', page, re.VERBOSE)
        for field in fields:
            post[field.group('name')] = ''

        result['post'] = post
        if unchecked:
            result['unchecked'] = unchecked
        return result

    def submit_form(self, data, *args, url=None, form=None, **kwargs):
        form = form or self.form(*args, **kwargs)
        form['post'].update(data)
        data_urlencoded = urllib.parse.urlencode(form['post']).encode('utf-8')
        url = url or form.get('url') or self.current_url
        content_type = form.get('enctype')
        ret = {
            'get': lambda: self.get(urllib.parse.urljoin(url, f'?{data_urlencoded}'), content_type=content_type),
            'post': lambda: self.get(url, form['post'], content_type=content_type),
        }[form['method'].lower()]()
        return ret

    def file_cache_clear(self):
        if self.limit_file_cache and self.counter_file_cache % self.limit_file_cache == 0:
            file_list = []
            for file_cache in listdir(self.dir_cache):
                stat_file = stat(self.dir_cache + file_cache)
                file_list.append((stat_file.st_atime, file_cache))
            file_list.sort(reverse=True)
            for atime, file_cache in file_list[self.limit_file_cache:]:
                remove(self.dir_cache + file_cache)
        self.counter_file_cache += 1

    def get_raw_cookies(self):
        for c in self.cookiejar:
            yield c

    def get_cookies(self):
        return dict(((i.name, i.value) for i in self.cookiejar))

    def get_cookie(self, name):
        return self.get_cookies().get(name, None)

    def set_cookie(self, name, value):
        for c in self.cookiejar:
            if c.name == name:
                c.value = value
                self.cookiejar.set_cookie(c)
                self.print("[setcookie]", name)
                break

    @staticmethod
    def rand_string(length):
        a = ascii_letters + digits
        return ''.join([choice(a) for i in range(length)])

    def save_cookie(self):
        if self.cookie_filename:
            try:
                self.cookiejar.save()
            except Exception:
                pass

    def close(self):
        if self.proxer:
            self.proxer.save_data()
        self.save_cookie()

    def __enter__(self):
        if self.opened is not True:
            self.opened = True
        return self

    def __exit__(self, *err):
        if self.opened is not False:
            self.opened = False
            self.close()

    def __del__(self):
        if not isdir(self.dir_cache):
            return

        for file_cache in listdir(self.dir_cache):
            diff_time = (datetime.now() - datetime.fromtimestamp(getctime(self.dir_cache + file_cache)))
            if diff_time.seconds >= self.cache_timeout:
                remove(self.dir_cache + file_cache)

        self.save_cookie()


if __name__ == "__main__":
    headers = [
        ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'),
        ('Accept-Encoding', 'gzip,deflate,sdch'),
        ('Accept-Language', 'ru-RU,ru;q=0.8,en-US;q=0.6,en;q=0.4'),
        ('Proxy-Connection', 'keep-alive'),
        ('User-Agent',
         'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
         'Ubuntu Chromium/37.0.2062.120 Chrome/37.0.2062.120 Safari/537.36'),
    ]
    req = requester(headers=headers)
    req.caching = False
    req.time_sleep = 1
    req.get("http://opencup.ru")
    req.get("http://clist.by")
    del req
