import asyncio
import logging
import re
import threading
import urllib.parse
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from itertools import count
from time import monotonic, time

from asgiref.sync import async_to_sync
from channels.layers import channel_layers, get_channel_layer
from django.core.cache import cache
from tqdm import tqdm as _tqdm

from logify.models import EventStatus

LIVE_LOG_QUEUE_SIZE = 256
LIVE_LOG_BATCH_SIZE = 50
LIVE_LOG_BATCH_INTERVAL = 0.05
LIVE_LOG_SEND_TIMEOUT = 2
LIVE_LOG_CLOSE_TIMEOUT = 3
LIVE_PROGRESS_INTERVAL = 0.5
LIVE_LOG_MESSAGE_LIMIT = 4096
LIVE_LOG_HISTORY_SIZE = 1000
LIVE_LOG_HISTORY_TIMEOUT = 24 * 60 * 60
LIVE_LOG_REDACTED = "<redacted>"

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
LIVE_LOG_URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^\s<>'\"`]+", re.IGNORECASE)
LIVE_LOG_SENSITIVE_NAME_RE = re.compile(
    r"[a-z0-9_-]*(?:api[-_ ]?(?:key|sig)|auth(?:entication|orization)?|cookie|credential|csrf|jwt|oauth|"
    r"pass(?:word|wd)?|private[-_ ]?key|secret|session(?:[-_ ]?(?:id|key))?|set[-_ ]?cookie|token)"
    r"[a-z0-9_-]*",
    re.IGNORECASE,
)
LIVE_LOG_SENSITIVE_PAIR_RE = re.compile(
    rf"""(?ix)
    (?P<prefix>
        (?<![\w?&/-])
        (?P<key_quote>["']?)
        {LIVE_LOG_SENSITIVE_NAME_RE.pattern}
        (?P=key_quote)
        \s*[:=]\s*
    )
    (?P<value>
        "(?:\\.|[^"\\])*"
        |
        '(?:\\.|[^'\\])*'
        |
        [^,\n}}\]]+
    )
    """
)
LIVE_LOG_SENSITIVE_TUPLE_RE = re.compile(
    rf"""(?ix)
    (?P<prefix>
        (?<!\w)
        (?P<key_quote>["'])
        {LIVE_LOG_SENSITIVE_NAME_RE.pattern}
        (?P=key_quote)
        \s*,\s*
    )
    (?P<value>
        "(?:\\.|[^"\\])*"
        |
        '(?:\\.|[^'\\])*'
    )
    """
)
LIVE_LOG_SENSITIVE_URL_PARAMETER_RE = re.compile(
    rf"(?P<prefix>[?&#](?:{LIVE_LOG_SENSITIVE_NAME_RE.pattern})=)[^&#\s]*",
    re.IGNORECASE,
)
TERMINAL_STATUSES = {"completed", "failed", "warning", "cancelled", "skipped", "interrupted"}

_current_session = ContextVar("live_log_session", default=None)
logger = logging.getLogger("logify.live")


def _redact_url_parameters(value):
    parameters = urllib.parse.parse_qsl(value, keep_blank_values=True)
    if not parameters:
        return value
    parameters = [
        (key, LIVE_LOG_REDACTED if LIVE_LOG_SENSITIVE_NAME_RE.search(key) else item) for key, item in parameters
    ]
    return urllib.parse.urlencode(parameters, doseq=True, safe="<>")


def _redact_live_url(match):
    value = match.group(0)
    suffix = ""
    while value and value[-1] in ".,;)]}":
        suffix = value[-1] + suffix
        value = value[:-1]
    try:
        parsed = urllib.parse.urlsplit(value)
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = f"{LIVE_LOG_REDACTED}@{netloc.rsplit('@', 1)[1]}"
        value = urllib.parse.urlunsplit((
            parsed.scheme,
            netloc,
            parsed.path,
            _redact_url_parameters(parsed.query),
            _redact_url_parameters(parsed.fragment),
        ))
    except Exception:
        value = re.sub(r"(?<=//)[^/@\s]+@", f"{LIVE_LOG_REDACTED}@", value)
        value = LIVE_LOG_SENSITIVE_URL_PARAMETER_RE.sub(
            lambda parameter_match: f"{parameter_match.group('prefix')}{LIVE_LOG_REDACTED}",
            value,
        )
    return value + suffix


def sanitize_live_text(message):
    try:
        message = ANSI_ESCAPE_RE.sub("", str(message))
        message = LIVE_LOG_URL_RE.sub(_redact_live_url, message)
        message = LIVE_LOG_SENSITIVE_TUPLE_RE.sub(
            lambda match: f'{match.group("prefix")}"{LIVE_LOG_REDACTED}"',
            message,
        )
        message = LIVE_LOG_SENSITIVE_PAIR_RE.sub(
            lambda match: f"{match.group('prefix')}{LIVE_LOG_REDACTED}",
            message,
        )
    except Exception:
        return LIVE_LOG_REDACTED
    if len(message) > LIVE_LOG_MESSAGE_LIMIT:
        message = f"{message[: LIVE_LOG_MESSAGE_LIMIT - 3]}..."
    return message


def get_live_log_group_name(event_log_id):
    return f"LIVE_EVENT_LOG__{event_log_id}"


def get_live_log_history_key(event_log_id):
    return f"live-event-log-history:{event_log_id}"


def clear_live_log_history(event_log_id):
    try:
        cache.delete(get_live_log_history_key(event_log_id))
    except Exception:
        logger.exception("Failed to clear live history for EventLog#%s", event_log_id)


def append_live_log_history(event_log_id, events):
    if not events:
        return
    try:
        key = get_live_log_history_key(event_log_id)
        history = cache.get(key, [])
        history.extend(events)
        cache.set(key, history[-LIVE_LOG_HISTORY_SIZE:], timeout=LIVE_LOG_HISTORY_TIMEOUT)
    except Exception:
        logger.exception("Failed to append live history for EventLog#%s", event_log_id)


def get_live_log_history(event_log_id, after_seq=0):
    try:
        history = cache.get(get_live_log_history_key(event_log_id), [])
    except Exception:
        logger.exception("Failed to read live history for EventLog#%s", event_log_id)
        return []
    return [event for event in history if event.get("seq", 0) > after_seq]


def publish_live_log_status(event_log_id, status, message=None):
    history = get_live_log_history(event_log_id)
    last_seq = max((event.get("seq", 0) for event in history), default=0)
    event = {
        "kind": "status",
        "seq": max(last_seq + 1, int(time() * 1000)),
        "timestamp": int(time()),
        "status": str(status),
    }
    if message:
        event["message"] = sanitize_live_text(message)
    append_live_log_history(event_log_id, [event])
    try:
        async_to_sync(get_channel_layer().group_send)(
            get_live_log_group_name(event_log_id),
            {
                "type": "live_log",
                "event_log_id": event_log_id,
                "events": [event],
            },
        )
    except Exception:
        logger.exception("Failed to publish live status for EventLog#%s", event_log_id)


def get_current_session():
    return _current_session.get()


def register_live_logger(command_logger):
    session = get_current_session()
    if session is not None:
        session.add_logger(command_logger)


class LiveLogHandler(logging.Handler):
    def __init__(self, session):
        super().__init__()
        self.session = session

    def emit(self, record):
        if getattr(record, "skip_live_log", False):
            return
        try:
            self.session.log(record.levelname, self.format(record), timestamp=record.created)
        except Exception:
            self.handleError(record)


class LiveLogSession:
    def __init__(
        self,
        event_log,
        command_logger=None,
        *,
        queue_size=LIVE_LOG_QUEUE_SIZE,
        batch_size=LIVE_LOG_BATCH_SIZE,
        batch_interval=LIVE_LOG_BATCH_INTERVAL,
        send_timeout=LIVE_LOG_SEND_TIMEOUT,
        close_timeout=LIVE_LOG_CLOSE_TIMEOUT,
        channel_layer_factory=None,
    ):
        self.event_log = event_log
        self.event_log_id = event_log.pk
        self.group_name = get_live_log_group_name(self.event_log_id)
        self.command_logger = command_logger
        self.queue_size = queue_size
        self.batch_size = batch_size
        self.batch_interval = batch_interval
        self.send_timeout = send_timeout
        self.close_timeout = close_timeout
        self.channel_layer_factory = channel_layer_factory or self._make_channel_layer

        self._events = deque()
        self._condition = threading.Condition()
        self._closing = False
        self._dropped = 0
        self._terminal_event = None
        self._sequence = count(1)
        self._bar_sequence = count(1)
        self._context_token = None
        self._handler = None
        self._loggers = []
        self._thread = None

    def __enter__(self):
        clear_live_log_history(self.event_log_id)
        self._context_token = _current_session.set(self)
        self._handler = LiveLogHandler(self)
        self._handler.setLevel(logging.INFO)
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self.add_logger(self.command_logger)
        self._thread = threading.Thread(
            target=self._sender,
            name=f"live-log-{self.event_log_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._handler is not None:
            for command_logger in self._loggers:
                command_logger.removeHandler(self._handler)
            self._handler.close()
            self._loggers.clear()
        if self._context_token is not None:
            _current_session.reset(self._context_token)
        with self._condition:
            self._closing = True
            self._condition.notify()
        if self._thread is not None:
            self._thread.join(timeout=self.close_timeout)

    def add_logger(self, command_logger):
        if command_logger is None or self._handler is None or command_logger in self._loggers:
            return
        command_logger.addHandler(self._handler)
        self._loggers.append(command_logger)

    def next_bar_id(self):
        return f"bar-{next(self._bar_sequence)}"

    @staticmethod
    def _make_channel_layer():
        return channel_layers.make_backend("default")

    def log(self, level, message, *, timestamp=None):
        message = sanitize_live_text(message)
        if timestamp is None:
            timestamp = time()
        self._enqueue({
            "kind": "log",
            "timestamp": int(timestamp),
            "level": level,
            "message": message,
        })

    def progress(self, **progress):
        if "description" in progress:
            progress["description"] = sanitize_live_text(progress["description"])
        self._enqueue({"kind": "progress", **progress})

    def status(self, status, message=None):
        event = {
            "kind": "status",
            "timestamp": int(time()),
            "status": str(status),
        }
        if message:
            event["message"] = sanitize_live_text(message)
        self._enqueue(event, terminal=str(status) in TERMINAL_STATUSES)

    def _enqueue(self, event, *, terminal=False):
        event["seq"] = next(self._sequence)
        with self._condition:
            if self._closing:
                return False
            if terminal:
                if self._dropped:
                    event["dropped_before"] = self._dropped
                    self._dropped = 0
                self._terminal_event = event
                self._condition.notify()
                return True
            if len(self._events) >= self.queue_size:
                self._dropped += 1
                return False
            if self._dropped:
                event["dropped_before"] = self._dropped
                self._dropped = 0
            self._events.append(event)
            self._condition.notify()
        return True

    def _next_batch(self):
        with self._condition:
            while not self._events and self._terminal_event is None and not self._closing:
                self._condition.wait()
            if not self._events and self._terminal_event is None:
                return None

            if self._terminal_event is not None:
                n_dropped = max(len(self._events) - self.batch_size + 1, 0)
                for _ in range(n_dropped):
                    self._events.popleft()
                if n_dropped:
                    self._terminal_event["dropped_before"] = self._terminal_event.get("dropped_before", 0) + n_dropped
                batch = list(self._events)
                self._events.clear()
                batch.append(self._terminal_event)
                self._terminal_event = None
                return batch

            deadline = monotonic() + self.batch_interval
            while len(self._events) < self.batch_size and not self._closing:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)

            batch = []
            while self._events and len(batch) < self.batch_size:
                batch.append(self._events.popleft())
            return batch

    def _sender(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        channel_layer = None
        try:
            channel_layer = self.channel_layer_factory()
            while True:
                batch = self._next_batch()
                if batch is None:
                    break
                message = {
                    "type": "live_log",
                    "event_log_id": self.event_log_id,
                    "events": batch,
                }
                try:
                    append_live_log_history(self.event_log_id, batch)
                    loop.run_until_complete(
                        asyncio.wait_for(
                            channel_layer.group_send(self.group_name, message),
                            timeout=self.send_timeout,
                        )
                    )
                except Exception:
                    logger.exception("Failed to send live log batch for EventLog#%s", self.event_log_id)
        finally:
            if channel_layer is not None and hasattr(channel_layer, "close_pools"):
                try:
                    loop.run_until_complete(asyncio.wait_for(channel_layer.close_pools(), timeout=0.5))
                except Exception:
                    logger.exception("Failed to close live log channel layer for EventLog#%s", self.event_log_id)
            loop.close()


@contextmanager
def stream_event_log(event_log, command_logger=None):
    with LiveLogSession(event_log, command_logger) as live_session:
        live_session.status(event_log.status, event_log.message)
        try:
            yield event_log
        except BaseException as e:
            event_log.update(status=EventStatus.FAILED, error=str(e))
            live_session.status(EventStatus.FAILED, str(e))
            raise
        else:
            if event_log.status == EventStatus.IN_PROGRESS:
                event_log.update_status(EventStatus.COMPLETED)
            live_session.status(event_log.status, event_log.message)


class tqdm(_tqdm):
    def __init__(self, *args, **kwargs):
        self._live_session = get_current_session()
        self._live_bar_id = self._live_session.next_bar_id() if self._live_session is not None else None
        self._live_last_display = float("-inf")
        self._live_completion = None
        super().__init__(*args, **kwargs)

    def close(self):
        was_disabled = getattr(self, "disable", True)
        super().close()
        total = getattr(self, "total", None)
        if not was_disabled and (total is None or self.n < total):
            self._publish_live_progress(finished=True)

    def display(self, msg=None, pos=None):
        ret = super().display(msg=msg, pos=pos)
        self._publish_live_progress()
        return ret

    def _publish_live_progress(self, *, finished=False):
        if self._live_session is None:
            return

        total = self.total
        completed = total is not None and self.n >= total
        completion = (self.n, total, self.desc) if completed else None
        current_time = monotonic()
        was_completed = self._live_completion is not None
        if (
            not finished
            and not completed
            and not was_completed
            and current_time - self._live_last_display < LIVE_PROGRESS_INTERVAL
        ):
            return
        if completed and completion == self._live_completion:
            return

        values = self.format_dict
        rate = values.get("rate")
        remaining = max(total - self.n, 0) if total is not None else None
        eta = remaining / rate if remaining is not None and rate else None
        progress = min(max(self.n / total, 0), 1) if total else None
        self._live_session.progress(
            bar_id=self._live_bar_id,
            description=self.desc or "",
            current=self.n,
            total=total,
            progress=progress,
            elapsed=values.get("elapsed"),
            rate=rate,
            eta=eta,
            completed=completed,
            finished=finished,
        )
        self._live_last_display = current_time
        self._live_completion = completion


def trange(*args, **kwargs):
    return tqdm(range(*args), **kwargs)
