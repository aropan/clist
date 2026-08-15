import asyncio
import atexit
import logging
import os
import threading
from concurrent.futures import Future
from queue import Queue

from django.conf import settings
from telegram import Bot as TelegramBot


class TelegramTransport:
    def __init__(self, token_getter, client_factory=TelegramBot):
        self._token_getter = token_getter
        self._client_factory = client_factory
        self._state_lock = threading.Lock()
        self._pid = None
        self._thread = None
        self._client = None
        self._initialized = False
        self._ready = None
        self._requests = None
        self._startup_error = None
        self._logger = logging.getLogger(__name__)

    def _after_fork(self):
        self._state_lock = threading.Lock()
        self._reset_state()

    def _reset_state(self):
        self._pid = None
        self._thread = None
        self._client = None
        self._initialized = False
        self._ready = None
        self._requests = None
        self._startup_error = None

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            token = self._token_getter()
            if not token:
                raise RuntimeError("TELEGRAM_TOKEN is not configured")
            self._client = self._client_factory(token=token)
        except Exception as error:
            self._startup_error = error
            self._ready.set()
            loop.close()
            return

        self._ready.set()
        while True:
            request = self._requests.get()
            if request is None:
                break
            method, args, kwargs, future = request
            try:
                result = loop.run_until_complete(self._invoke(method, args, kwargs))
            except BaseException as error:
                future.set_exception(error)
            else:
                future.set_result(result)

        if self._initialized:
            try:
                loop.run_until_complete(self._client.shutdown())
            except Exception:
                self._logger.exception("Failed to shut down Telegram client")
        loop.close()

    def _ensure_started(self):
        pid = os.getpid()
        with self._state_lock:
            if self._pid == pid and self._thread is not None and self._thread.is_alive():
                ready = self._ready
            else:
                self._reset_state()
                self._pid = pid
                self._ready = threading.Event()
                self._requests = Queue()
                self._thread = threading.Thread(
                    target=self._run,
                    name="telegram-transport",
                    daemon=True,
                )
                self._thread.start()
                ready = self._ready

        if not ready.wait(timeout=10):
            raise RuntimeError("Timed out while starting Telegram transport")
        if self._startup_error is not None:
            raise self._startup_error

    async def _invoke(self, method, args, kwargs):
        if not self._initialized:
            await self._client.initialize()
            self._initialized = True
        return await getattr(self._client, method)(*args, **kwargs)

    def request(self, method, *args, **kwargs):
        self._ensure_started()
        future = Future()
        self._requests.put((method, args, kwargs, future))
        return future.result()

    def close(self):
        with self._state_lock:
            if self._pid != os.getpid() or self._requests is None or self._thread is None:
                return
            thread = self._thread
            self._requests.put(None)

        if thread is not threading.current_thread():
            thread.join(timeout=10)
        with self._state_lock:
            self._reset_state()


telegram_transport = TelegramTransport(lambda: settings.TELEGRAM_TOKEN)
atexit.register(telegram_transport.close)
if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=telegram_transport._after_fork)
