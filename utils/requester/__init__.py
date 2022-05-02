#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-


import atexit
import copy
import html
import json
import logging
import mimetypes
import random
import re
import string
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from distutils.util import strtobool
from gzip import GzipFile
from hashlib import md5
from http.cookiejar import Cookie, MozillaCookieJar
from io import BytesIO
from json import dumps, load, loads
from os import environ, listdir, makedirs, path, remove, stat
from os.path import getctime, isdir
from random import choice, gauss
from string import ascii_letters, digits
from sys import stderr
from time import sleep

import chardet
from filelock import FileLock
from fp.fp import FreeProxy

logging.getLogger('chardet.charsetprober').setLevel(logging.INFO)


class FileWithProxiesNotFound(Exception):
    pass


class NotFoundProxy(Exception):
    pass


class ProxyLimitReached(Exception):
    pass


class FailOnGetResponse(Exception):

    @property
    def code(self):
        return getattr(self.args[0], 'code', None)

    def __str__(self):
        err = self.args[0]
        if not hasattr(self, 'error_'):
            self.error_ = super().__str__()
            if hasattr(err, 'fp'):
                response = err.fp.read()
                try:
                    response = json.loads(response)
                except Exception:
                    pass
                self.error_ += ', response = ' + str(response)
        return self.error_


class NoVerifyWord(Exception):
    pass


class proxer():
    DIVIDER = 3
    LIMIT_TIME = 2.5

    def load_data(self):
        try:
            with open(self.file_name, "r") as fo:
                self.data = load(fo)
        except (IOError, ValueError):
            self.data = {}

    def check_proxy(self):
        if (self.proxy and self.proxy["_fail"] > 0 and self.proxy["_success"] == 0 or self.is_slow_proxy()):
            self.print(f'remove {self.proxy_key}, info = {self.proxy}')
            del self.data[self.proxy_key]
            self.proxy = None
            self.proxy_key = None
            self.save_data()
            if not self.without_new_proxy and self.callback_new_proxy:
                proxy = self.get()
                self.callback_new_proxy(proxy)

    def save_data(self):
        self.check_proxy()
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
            time = self.time_response()
            return time > self.time_limit

    @staticmethod
    def get_timestamp():
        return int(datetime.utcnow().strftime("%s"))

    @staticmethod
    def get_score(proxy):
        return (proxy["_success"], -proxy["_timestamp"])

    def add(self, proxy):
        value = self.data.setdefault(str(proxy), {})
        if isinstance(proxy, str):
            value["addr"], value["port"] = proxy.split(":")
        else:
            value["addr"] = proxy.host
            value["port"] = proxy.port
        value.setdefault("_success", 0)
        value.setdefault("_fail", 0)
        value.setdefault("_timestamp", self.get_timestamp())

    def add_free_proxies(self):
        for proxy in FreeProxy().get_proxy_list():
            self.add(proxy)

    def is_alive(self):
        return self.n_limit is None or self.n_limit > 0

    def get(self):
        if self.n_limit is not None:
            if self.n_limit <= 0:
                raise ProxyLimitReached()
            self.n_limit -= 1

        if not self.data:
            self.add_free_proxies()
        self.proxy = None
        for k, v in self.data.items():
            if self.proxy is None or self.get_score(v) > self.get_score(self.proxy):
                self.proxy = v
                self.proxy_key = k
        if not self.proxy:
            raise NotFoundProxy()
        self.proxy["_timestamp"] = self.get_timestamp()
        ret = "%(addr)s:%(port)s" % self.proxy
        self.print(f'get = {ret} of {len(self)} (limit = {self.n_limit}), time = {self.time_response()}')
        return ret

    def ok(self, time_response=None):
        if not self.proxy:
            return
        self.proxy["_success"] += 1
        if time_response:
            self.proxy.setdefault("_count", 0)
            self.proxy.setdefault("_total_time", 0.)
            self.proxy["_count"] += 1
            self.proxy["_total_time"] += time_response.total_seconds() + time_response.microseconds / 1000000.
        self.print(f'ok, {time_response} with average {self.time_response()}')
        self.check_proxy()

    def fail(self, error):
        if not self.proxy:
            return
        self.print('fail', str(error)[:80])
        self.proxy["_success"] //= self.DIVIDER
        self.proxy["_fail"] += 1
        self.check_proxy()

    def time_response(self):
        if self.proxy and self.proxy.get("_count", 0):
            return round(self.proxy["_total_time"] / self.proxy["_count"], 3)

    def print(self, *args):
        if self.logger:
            self.logger('[proxy]', *args)

    def get_connect_ret(self):
        return self.connect_ret

    def set_connect_func(self, func):
        self.connect_func = func
        self.connect_ret = None

    def connect(self, req, set_proxy):
        if self.connect_func:
            self.without_new_proxy = True
            while True:
                try:
                    self.connect_ret = self.connect_func(req)
                except FailOnGetResponse:
                    set_proxy(self.get())
                    continue
                break
            self.without_new_proxy = False
        return self.connect_ret

    def __init__(
        self,
        file_name,
        callback_new_proxy=None,
        logger=None,
        connect=None,
        time_limit=LIMIT_TIME,
        n_limit=None,
    ):
        self.logger = logger
        self.file_name = file_name + ".json"
        self.time_limit = time_limit
        self.callback_new_proxy = callback_new_proxy
        self.without_new_proxy = False
        self.connect_func = connect
        self.connect_ret = None
        self.load_data()
        self.n_limit = n_limit
        if path.exists(file_name):
            with open(file_name, "r") as fo:
                for line in fo:
                    line = line.strip()
                    if not line:
                        continue
                    self.add(line)
            open(file_name, "w").close()
        self.proxy = None

    def __len__(self):
        return len(self.data)

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
    dir_cache = path.dirname(path.abspath(__file__)) + "/cache/"
    cookie_filename = path.join(path.dirname(path.abspath(__file__)), ".cookie")
    default_filepath_proxies = path.join(path.dirname(__file__), "proxies.txt")
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
                 file_name_with_proxies=default_filepath_proxies):
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
        self._init_opener_headers = self.headers
        self.init_opener()
        self.set_proxy(proxy, file_name_with_proxies)
        atexit.register(self.cleanup)

    def init_opener(self):
        if self.cookie_filename:
            makedirs(path.dirname(self.cookie_filename), exist_ok=True)
            self.cookiejar = MozillaCookieJar(self.cookie_filename)
            if path.exists(self.cookie_filename):
                self.cookiejar.load(ignore_discard=True, ignore_expires=True)
        else:
            self.cookiejar = MozillaCookieJar()

        self.http_cookie_processor = urllib.request.HTTPCookieProcessor(self.cookiejar)
        self.opener = urllib.request.build_opener(self.http_cookie_processor)
        self.proxer = None

    def set_proxy(self, proxy, filepath_proxies=default_filepath_proxies, **kwargs):
        if proxy is True:
            self.proxer = proxer(filepath_proxies, callback_new_proxy=self.set_proxy, logger=self.print, **kwargs)
            proxy = self.proxer.get()

        if proxy:
            def set_proxy(proxy):
                self.opener.add_handler(urllib.request.ProxyHandler({
                    'http': proxy,
                    'https': proxy,
                }))

            set_proxy(proxy)

            if self.proxer:
                self.proxer.connect(req=self, set_proxy=set_proxy)

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
        return_last_url=False,
        return_json=False,
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

        if post and isinstance(post, dict):
            post_urlencoded = urllib.parse.urlencode(post).encode('utf-8')
        elif isinstance(post, str):
            post_urlencoded = post.encode('utf8')
        else:
            post_urlencoded = post

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
        self.print(("[cache] " if from_cache else "") + url, force=from_cache)
        self.error = None
        response = None
        last_url = None
        if from_cache:
            with open(file_cache, "r") as f:
                page = f.read()
        else:
            if self.proxer and not self.proxer.is_alive():
                raise ProxyLimitReached()
            if self.time_sleep:
                v_time_sleep = min(1, abs(gauss(0, 1)) * self.time_sleep)
                sleep(v_time_sleep)
            if not headers:
                headers = {}
            if self.ref_url and 'Referer' not in headers:
                headers.update({"Referer": self.ref_url})
            if self.last_url:
                prev = urllib.parse.urlparse(self.last_url)
                curr = urllib.parse.urlparse(url)
                if prev.netloc != curr.netloc or prev.path != curr.path:
                    self.opener.addheaders = self._init_opener_headers
            else:
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

                time_out = time_out or self.time_out
                if self.proxer:
                    time_out = min(time_out, self.proxer.time_limit)
                response = self.opener.open(
                    request,
                    post_urlencoded if post else None,
                    timeout=time_out,
                )
                last_url = response.geturl() if response else url
                if return_last_url:
                    return last_url
                if response.info().get("Content-Encoding", None) == "gzip":
                    buf = BytesIO(response.read())
                    page = GzipFile(fileobj=buf).read()
                else:
                    page = response.read()
                self.time_response = datetime.utcnow() - time_start
                if self.verify_word and self.verify_word not in page:
                    raise NoVerifyWord("No verify word '%s', size page = %d" % (self.verify_word, len(page)))
            except Exception as err:
                self.print('[error]', str(err)[:80])
                self.error = err
                if self.assert_on_fail:
                    if self.proxer:
                        self.proxer.fail(err)
                    raise FailOnGetResponse(err)
                else:
                    traceback.print_exc()
                return

            response_content_type = response.info().get('Content-Type')

            try:
                if file_cache and caching:
                    cookie_write = True
                    if response_content_type.startswith('application/json'):
                        page = dumps(loads(page), indent=4)
                        cookie_write = False
                    if response_content_type.startswith('image/'):
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

            if not response_content_type or not response_content_type.startswith('image/'):
                matches = re.findall(r'charset=["\']?(?P<charset>[^"\'\s\.>;]{3,}\b)', str(page), re.IGNORECASE)
                if matches and detect_charsets is not None:
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
                    try:
                        page = page.decode(charset, 'replace')
                    except LookupError:
                        pass

        self.last_page = page
        if is_ref_url:
            self.ref_url = self.last_url
        self.file_cache_clear()
        self.response = response
        self.last_url = last_url

        if return_json and response_content_type.startswith('application/json'):
            page = json.loads(page)

        return (page, last_url) if return_url else page

    @property
    def current_url(self):
        return self.last_url

    def head(self, url):
        return self.opener.open(url).getheaders()

    def geturl(self, url):
        return self.opener.open(url).geturl()

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

    def form(self, page=None, name=None, action='', limit=1, fid=None, selectors=(), enctype=False):
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
        if name is not None:
            selectors.append('name="(?P<name>[^"]*)"')
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

    def get_cookies(self, domain_regex=None):
        return dict((
            (i.name, i.value)
            for i in self.cookiejar
            if domain_regex is None or re.search(domain_regex, i.domain)
        ))

    def get_cookie(self, name, *args, **kwargs):
        return self.get_cookies(*args, **kwargs).get(name, None)

    def set_cookie(self, name, value):
        for c in self.cookiejar:
            if c.name == name:
                c.value = value
                self.cookiejar.set_cookie(c)
                self.print("[setcookie]", name)
                break

    def update_cookie(self, c):
        self.cookiejar.set_cookie(c)

    def add_cookie(self, name, value, domain=None, path='/', expires=None):
        if expires is None:
            expires = (datetime.now() + timedelta(days=365)).timestamp()

        c = Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=domain or urllib.parse.urlparse(self.last_url).netloc,
            domain_specified=False,
            domain_initial_dot=False,
            path='/',
            path_specified=True,
            secure=False,
            expires=expires,
            discard=False,
            comment=None,
            comment_url=None,
            rest={'HttpOnly': None},
            rfc2109=False,
        )
        self.cookiejar.set_cookie(c)

    @staticmethod
    def rand_string(length):
        a = ascii_letters + digits
        return ''.join([choice(a) for i in range(length)])

    def save_cookie(self):
        if self.cookie_filename and hasattr(self, 'cookiejar'):
            lock = FileLock(self.cookie_filename)
            with lock.acquire(timeout=60):
                self.cookiejar.save(self.cookie_filename, ignore_discard=True, ignore_expires=True)

    def close(self):
        if self.proxer:
            self.proxer.save_data()
        self.save_cookie()

    def __call__(self, with_proxy=False, args_proxy=None):
        if with_proxy:
            ret = copy.copy(self)
            ret.init_opener()
            args_proxy = args_proxy or {}
            ret.set_proxy(proxy=True, **args_proxy)
            return ret
        return self

    def __enter__(self):
        return self

    def __exit__(self, *err):
        self.close()

    def cleanup(self):
        self.save_cookie()

        if not isdir(self.dir_cache):
            return

        for file_cache in listdir(self.dir_cache):
            diff_time = (datetime.now() - datetime.fromtimestamp(getctime(self.dir_cache + file_cache)))
            if diff_time.seconds >= self.cache_timeout:
                remove(self.dir_cache + file_cache)


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
