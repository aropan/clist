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
import ssl
import string
import subprocess
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zlib
from contextlib import contextmanager
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

import brotli
import chardet
from filelock import FileLock
from requests.models import Response

from utils.proxy_list import ProxyList

logging.getLogger('chardet.charsetprober').setLevel(logging.INFO)
logger = logging.getLogger('utils.requester')


class BaseException(Exception):

    def __init__(self, *args):
        super().__init__(*args)

    def __str__(self):
        return f'{self.__class__.__name__}: {super().__str__()}'


class FileWithProxiesNotFound(BaseException):
    pass


class NotFoundProxy(BaseException):
    pass


class ProxyLimitReached(BaseException):
    pass


class FailOnGetResponse(BaseException):

    @property
    def code(self):
        return getattr(self.args[0], 'code', None)

    @property
    def url(self):
        return getattr(self.args[0], 'url', None)

    @property
    def response(self):
        if not hasattr(self, 'response_'):
            err = self.args[0]
            self.response_ = read_response(err).decode() if hasattr(err, 'fp') else None
        return self.response_

    def has_message(self, message):
        response = self.response
        return response is not None and message in self.response


class CurlFailedResponse(FailOnGetResponse):

    def __getattr__(self, name):
        return getattr(self.args[0], name, None)


def raise_fail(err):
    exc = FailOnGetResponse(err)
    if exc.code or exc.url:
        msg = f'code = {exc.code}, url = `{exc.url}`'
        if exc.response:
            response = exc.response.strip().replace('\n', '\\n')
            if len(response) > 200:
                response = response[:200] + '...'
            msg += f', response = `{response}`'
        logger.warning(msg)
    raise exc from err


class NoVerifyWord(Exception):
    pass


class proxer():
    DIVIDER = 3
    LIMIT_TIME = 2.5

    def load_data(self):
        try:
            with open(self.file_name, 'r') as fo:
                self._data = load(fo)
        except (IOError, ValueError):
            self._data = {}
        self._data.setdefault('proxies', {})
        self._data.setdefault('sources', {})

    def clear_data(self):
        created_threshold = self.get_timestamp() - 60 * 60
        removed = []
        for k, v in self.proxies.items():
            if v['_success'] == 0 and v.get('_created', -1) < created_threshold:
                removed.append(k)
        for k in removed:
            del self.proxies[k]
        self.print(f'remove {len(removed)} proxies')

    @property
    def proxies(self):
        return self._data['proxies']

    @property
    def sources(self):
        return self._data['sources']

    def check_proxy(self):
        with self.lock:
            if (self.proxy and self.proxy['_fail'] > 0 and self.proxy['_success'] == 0 or self.is_slow_proxy()):
                self.print(f'remove {self.proxy_key}, info = {self.proxy}')
                del self.proxies[self.proxy_key]
                self.proxy = None
                self.proxy_key = None
                self.save_data()
                if not self.without_new_proxy and self.callback_new_proxy:
                    proxy = self.get()
                    self.callback_new_proxy(proxy)

    def save_data(self):
        with self.lock:
            self.check_proxy()
            j = dumps(
                self._data,
                indent=4,
                sort_keys=True,
                ensure_ascii=False
            )
            with open(self.file_name, 'w') as fo:
                fo.write(j)

    def is_slow_proxy(self):
        if self.proxy and self.proxy.get('_total_count', 0) > 9:
            time = self.time_response()
            return time > self.time_limit

    @staticmethod
    def get_timestamp():
        return int(datetime.utcnow().strftime('%s'))

    @staticmethod
    def get_score(proxy):
        return (proxy['_success'], -proxy['_timestamp'])

    def add(self, proxy):
        if isinstance(proxy, str):
            addr, port = proxy.split(':')
            proxy = {'addr': addr, 'port': port}
        key = f'{proxy["addr"]}:{proxy["port"]}'
        value = self.proxies.setdefault(key, {})
        value.update(proxy)
        value.setdefault('_success', 0)
        value.setdefault('_fail', 0)
        value.setdefault('_created', self.get_timestamp())
        value.setdefault('_timestamp', self.get_timestamp())

    def add_free_proxies(self):
        for proxy in ProxyList().get():
            self.add(proxy)

    def is_alive(self):
        return self.n_limit is None or self.n_limit > 0

    @property
    def proxy_address(self):
        try:
            return '%(addr)s:%(port)s' % self.proxy
        except Exception:
            return None

    def get(self):
        if self.n_limit is not None:
            if self.n_limit <= 0:
                raise ProxyLimitReached()
            self.n_limit -= 1

        if not self.proxies:
            self.add_free_proxies()
        self.proxy = None
        for k, v in self.proxies.items():
            if self.proxy is None or self.get_score(v) > self.get_score(self.proxy):
                self.proxy = v
                self.proxy_key = k
        if not self.proxy:
            raise NotFoundProxy()
        self.proxy['_timestamp'] = self.get_timestamp()
        ret = self.proxy_address
        self.print(f'get = {ret} of {len(self)} (limit = {self.n_limit}), time = {self.time_response()}')
        return ret

    def update_value(self, key, value):
        self.proxy.setdefault(key, 0)
        self.proxy[key] += value
        if 'source' in self.proxy:
            source = self.sources.setdefault(self.proxy['source'], {})
            source.setdefault(key, 0)
            source[key] += value

    def ok(self, proxy, time_response=None):
        with self.lock:
            if not self.proxy or proxy != self.proxy_address:
                return
            self.update_value('_success', 1)
            if time_response:
                delta_time = time_response.total_seconds() + time_response.microseconds / 1000000.
                self.update_value('_total_count', 1)
                self.update_value('_total_time', delta_time)
                self.proxy['_avg_time'] = self.time_response()
            self.print(f'ok, {time_response} with average {self.time_response()}')
            self.check_proxy()

    def fail(self, proxy):
        with self.lock:
            if not self.proxy or proxy != self.proxy_address:
                return
            self.proxy['_success'] //= self.DIVIDER
            self.update_value('_fail', 1)
            self.check_proxy()

    def time_response(self):
        if self.proxy and self.proxy.get('_total_count', 0):
            return round(self.proxy['_total_time'] / self.proxy['_total_count'], 3)

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
                    with self.lock:
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
        self.file_name = file_name + '.json'
        self.time_limit = time_limit
        self.callback_new_proxy = callback_new_proxy
        self.without_new_proxy = False
        self.connect_func = connect
        self.connect_ret = None
        self.load_data()
        self.clear_data()
        self.n_limit = n_limit
        if path.exists(file_name):
            with open(file_name, 'r') as fo:
                for line in fo:
                    line = line.strip()
                    if not line:
                        continue
                    self.add(line)
            open(file_name, 'w').close()
        self.proxy = None
        self.lock = threading.RLock()

    def __len__(self):
        return len(self.proxies)

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


@contextmanager
def get_response_buffer(response):
    content_encoding = response.info().get("Content-Encoding", None)
    if content_encoding == 'gzip':
        buf = BytesIO(response.read())
        with GzipFile(fileobj=buf) as f:
            yield f
    elif content_encoding == 'deflate':
        yield BytesIO(zlib.decompress(response.read(), -zlib.MAX_WBITS))
    elif content_encoding == 'br':
        yield BytesIO(brotli.decompress(response.read()))
    else:
        yield response


def read_response(response):
    with get_response_buffer(response) as buf:
        return buf.read()


def curl_response(url, headers=None, cookie_file=None):
    args = ['curl', '-i', url, '-L', '--compressed']
    if cookie_file:
        args.extend(['-b', cookie_file, '-c', cookie_file])
    if headers:
        for k, v in headers.items():
            args.extend(['-H', f'{k}: {v}'])

    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()

    output = stdout.decode('utf-8')
    headers_raw, body = output.split('\r\n\r\n', 1)
    headers_lines = headers_raw.split('\r\n')

    response = Response()
    response._content = body.encode('utf-8')

    for header in headers_lines[1:]:
        key, value = header.split(": ", 1)
        if key.lower() == 'content-encoding':
            continue
        response.headers[key] = value

    status_line = headers_lines[0].split(' ')
    response.code = int(status_line[1])
    response.reason = ' '.join(status_line[2:])
    response.url = url
    response.info = lambda *args, **kwargs: response.headers
    response.read = lambda: response._content
    return response


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
    n_attempts = int(environ.get('REQUESTER_N_ATTEMPTS', 1))
    attempt_delay = int(environ.get('REQUESTER_ATTEMPT_DELAY', 2))
    additional_lock = threading.Lock()

    def print(self, *objs, force=False):
        if self.debug_output or force:
            print(datetime.utcnow(), *objs, file=stderr)

    def __init__(self,
                 proxy=environ.get('REQUESTER_PROXY'),
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
                ('Accept-Encoding', 'gzip, deflate, br'),
                ('Accept-Language', 'ru-ru,ru;q=0.8,en-us;q=0.5,en;q=0.3'),
                ('Connection', 'keep-alive'),
                (
                    'User-Agent',
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'  # noqa
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

        http_cookie_processor = urllib.request.HTTPCookieProcessor(self.cookiejar)
        context = ssl.create_default_context()
        context.set_ciphers('DEFAULT')
        if strtobool(environ.get('REQUESTER_INSECURE', '0')):
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        https_handler = urllib.request.HTTPSHandler(context=context)
        self.opener = urllib.request.build_opener(http_cookie_processor, https_handler)
        self.proxer = None
        self.proxy = None

    def set_proxy(self, proxy, filepath_proxies=default_filepath_proxies, **kwargs):
        if proxy is True or proxy == 'true':
            self.proxer = proxer(filepath_proxies, callback_new_proxy=self.set_proxy, logger=self.print, **kwargs)
            proxy = self.proxer.get()

        if proxy:
            def set_proxy(proxy):
                self.opener.add_handler(urllib.request.ProxyHandler({
                    'http': proxy,
                    'https': proxy,
                }))
                self.proxy = proxy

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
        return_code=False,
        force_json=False,
        ignore_codes=None,
        n_attempts=None,
        additional_attempts=None,
        additional_delay=0,
        last_info=True,
        params=None,
        with_curl=False,
        with_referer=True,
        curl_cookie_file=None,
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

        if params:
            url = f'{url}?{urllib.parse.urlencode(params)}'

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
        page, self.error, response, last_url, proxy = None, None, None, None, None
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
            if self.last_url:
                prev = urllib.parse.urlparse(self.last_url)
                curr = urllib.parse.urlparse(url)
                if with_referer and 'Referer' not in headers and prev.netloc == curr.netloc:
                    headers.update({"Referer": self.last_url})
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
                headers.update({"Content-Type": content_type})

            n_attempts = n_attempts or self.n_attempts
            attempt = 0
            while attempt < n_attempts:
                page, self.error, response, last_url, proxy = None, None, None, None, None
                attempt_delay = self.attempt_delay * attempt / n_attempts
                try:
                    if headers:
                        request = urllib.request.Request(url, headers=headers)
                    else:
                        request = url

                    time_start = datetime.utcnow()

                    time_out = time_out or self.time_out
                    if self.proxer:
                        time_out = min(time_out, self.proxer.time_limit)
                    proxy = self.proxy

                    if with_curl:
                        response = curl_response(url, headers=headers, cookie_file=curl_cookie_file)
                        if response.code != 200:
                            raise CurlFailedResponse(response)
                        last_url = url
                    else:
                        response = self.opener.open(
                            request,
                            post_urlencoded if post else None,
                            timeout=time_out,
                        )
                        last_url = response.geturl() if response else url

                    if return_last_url:
                        return last_url
                    page = read_response(response)
                except Exception as err:
                    with_error_code = isinstance(err, (urllib.error.HTTPError, CurlFailedResponse))
                    error_code = err.code if with_error_code else None
                    if ignore_codes and error_code in ignore_codes:
                        force_json = False
                        response = err
                        page = read_response(response)
                    else:
                        self.print(f'[error] code = {error_code}, response = {str(err)[:200]}')
                        self.error = err
                        if self.proxer:
                            self.proxer.fail(proxy=str(proxy))

                        if additional_attempts and error_code in additional_attempts:
                            additional_attempt = additional_attempts[error_code]
                            if (
                                additional_attempt['count'] > 0 and
                                ('func' not in additional_attempt or additional_attempt['func'](FailOnGetResponse(err)))
                            ):
                                additional_attempt['count'] -= 1
                                attempt -= 1
                                with self.additional_lock:
                                    sleep(additional_delay)

                        attempt += 1
                        if attempt < n_attempts:
                            sleep(attempt_delay)
                            continue
                        if self.assert_on_fail:
                            raise_fail(err)
                        else:
                            traceback.print_exc()
                        return
                break

            self.time_response = datetime.utcnow() - time_start
            if page and self.verify_word and self.verify_word not in page:
                raise NoVerifyWord("No verify word '%s', size page = %d" % (self.verify_word, len(page)))

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

            if self.proxer and not self.error:
                self.proxer.ok(proxy=str(proxy), time_response=self.time_response)

            if page and (not response_content_type or not response_content_type.startswith('image/')):
                matches = re.findall(r'charset=["\']?(?P<charset>[^"\'\s\.>;,]{3,}\b)', str(page), re.IGNORECASE)
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

        self.file_cache_clear()

        if last_info:
            self.last_page = page
            if is_ref_url:
                self.ref_url = self.last_url
            self.response = response
            self.last_url = last_url

        if page and return_json:
            if response_content_type.startswith('application/json') or force_json:
                page = json.loads(page)
            else:
                page = {'page': page, '__no_json': True}
        if return_url:
            return page, last_url
        if return_code:
            return page, response.code
        return page

    @property
    def current_url(self):
        return self.last_url

    def head(self, url):
        return self.opener.open(url).getheaders()

    def geturl(self, url):
        try:
            return self.opener.open(url).geturl()
        except urllib.error.URLError:
            return None

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
            path=path,
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

    def with_proxy(self, inplace=True, attributes=None, **kwargs):
        self.save_cookie()
        if inplace:
            ret = self
        else:
            ret = copy.copy(self)
            ret.init_opener()
        ret.set_proxy(proxy=True, **kwargs)
        if attributes:
            orig_attributes = {}
            for field, value in attributes.items():
                orig_attributes[field] = getattr(ret, field, None)
                setattr(ret, field, value)
            setattr(ret, 'orig_attributes', orig_attributes)
        return ret

    def __enter__(self):
        return self

    def __exit__(self, *err):
        orig_attributes = getattr(self, 'orig_attributes', None)
        if orig_attributes:
            for field, value in orig_attributes.items():
                setattr(self, field, value)
        self.close()
        self.init_opener()

    def cleanup(self):
        self.save_cookie()

        if not isdir(self.dir_cache):
            return

        for file_cache in listdir(self.dir_cache):
            diff_time = (datetime.now() - datetime.fromtimestamp(getctime(self.dir_cache + file_cache)))
            if diff_time.seconds >= self.cache_timeout:
                remove(self.dir_cache + file_cache)
