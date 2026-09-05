#!/usr/bin/env python

import glob
import hashlib
import logging
import os
import re
from collections import Counter
from datetime import UTC, datetime, timedelta

import coloredlogs
import yaml
from django.core.management.base import BaseCommand
from django.utils import timezone

from clist.templatetags.extras import md_escape
from tg.bot import Bot

logger = logging.getLogger("notify.error")
coloredlogs.install(logger=logger)


class Command(BaseCommand):
    help = "Notify errors"
    ERROR_RETENTION = timedelta(days=1)
    ERROR_TIMESTAMP_RE = re.compile(
        r"^(?:\[\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\]|"
        r"\d{4}[.-]\d{2}[.-]\d{2}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s*"
    )
    PHP_ERROR_RE = re.compile(
        r"PHP (?P<level>Warning|Notice|Deprecated|Fatal error|Parse error):\s*"
        r"(?P<message>.*?)\s+in\s+(?P<path>\S+\.php)\s+on\s+line\s+(?P<line>\d+)",
        re.DOTALL | re.IGNORECASE,
    )

    @staticmethod
    def _extract_errors(content, regex, flags=re.MULTILINE | re.IGNORECASE):
        return [match.group(0) for match in re.finditer(regex, content, flags)]

    @classmethod
    def _extract_php_errors(cls, content):
        errors = []
        for match in cls.PHP_ERROR_RE.finditer(content):
            message = match.group("message").splitlines()[0].strip()
            errors.append(
                f"PHP {match.group('level')}: {message} in {match.group('path')} on line {match.group('line')}"
            )
        return errors

    @classmethod
    def _error_signature(cls, error):
        normalized_error = cls.ERROR_TIMESTAMP_RE.sub("", error)
        return hashlib.sha256(normalized_error.encode("utf8")).hexdigest()

    @staticmethod
    def _file_id(content, file_stat):
        first_line = content.partition("\n")[0].rstrip("\r")
        if first_line.startswith("BEGIN "):
            return first_line
        return f"{file_stat.st_dev}:{file_stat.st_ino}"

    @staticmethod
    def _parse_timestamp(value):
        if isinstance(value, datetime):
            timestamp = value
        elif isinstance(value, str):
            try:
                timestamp = datetime.fromisoformat(value)
            except ValueError:
                return None
        else:
            return None
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return timestamp

    def _update_error_cache(self, cache, key, errors, file_id, file_size, current_time):
        file_state = cache.get(key)
        if not isinstance(file_state, dict) or not isinstance(file_state.get("errors"), dict):
            file_state = {"errors": {}}
            cache[key] = file_state

        file_reset = file_state.get("file_id") != file_id or file_size < file_state.get("file_size", 0)
        if file_reset:
            for error_state in file_state["errors"].values():
                if isinstance(error_state, dict):
                    error_state["file_occurrences"] = 0

        file_state["file_id"] = file_id
        file_state["file_size"] = file_size

        current_signatures = {}
        for error, count in Counter(errors).items():
            signature = self._error_signature(error)
            if signature in current_signatures:
                _, previous_count = current_signatures[signature]
                count += previous_count
            current_signatures[signature] = (error, count)
        new_errors = []
        timestamp = current_time.isoformat()

        for signature, (error, occurrences) in current_signatures.items():
            error_state = file_state["errors"].get(signature)
            if not isinstance(error_state, dict):
                error_state = {
                    "message": error,
                    "first_seen": timestamp,
                    "last_seen": timestamp,
                    "count": 0,
                    "file_occurrences": 0,
                }
                file_state["errors"][signature] = error_state
                new_errors.append(error)

            previous_occurrences = error_state.get("file_occurrences", 0)
            error_state["count"] = error_state.get("count", 0) + max(occurrences - previous_occurrences, 0)
            error_state["last_seen"] = timestamp
            error_state["message"] = error
            error_state["file_occurrences"] = occurrences

        cutoff = current_time - self.ERROR_RETENTION
        for signature, error_state in list(file_state["errors"].items()):
            if signature in current_signatures:
                continue
            last_seen = self._parse_timestamp(error_state.get("last_seen")) if isinstance(error_state, dict) else None
            if last_seen is None or last_seen < cutoff:
                del file_state["errors"][signature]

        if not file_state["errors"]:
            del cache[key]

        return new_errors

    def _check(
        self,
        filepath,
        cache,
        key,
        regex=None,
        href=None,
        flags=re.MULTILINE | re.IGNORECASE,
        extractor=None,
        require_complete=False,
        current_time=None,
    ):
        if not os.path.exists(filepath):
            logger.warning(f"skip {filepath}")
            return
        logger.info(f"check {filepath}")
        with open(filepath) as fo:
            content = fo.read()
            file_stat = os.fstat(fo.fileno())

        stripped_content = content.rstrip()
        starts_with_begin = content.startswith("BEGIN ")
        last_line = stripped_content.rpartition("\n")[2]
        is_complete = bool(stripped_content) and last_line.startswith("END ")
        if (require_complete or starts_with_begin) and not is_complete:
            logger.info(f"skip incomplete {filepath}")
            return

        errors = extractor(content) if extractor else self._extract_errors(content, regex, flags)
        errors = [error for error in errors if "contest = " not in error]
        for error in errors:
            logger.warning(error)

        new_errors = self._update_error_cache(
            cache,
            key,
            errors,
            self._file_id(content, file_stat),
            file_stat.st_size,
            current_time or timezone.now(),
        )
        if new_errors:
            errors_message = "\n".join(new_errors)
            msg = f"{md_escape(href or key)}\n```\n{errors_message}\n```"
            self._bot.admin_message(msg)

    def _cleanup_error_cache(self, cache, current_time):
        cutoff = current_time - self.ERROR_RETENTION
        for key, file_state in list(cache.items()):
            if not isinstance(file_state, dict) or not isinstance(file_state.get("errors"), dict):
                del cache[key]
                continue
            for signature, error_state in list(file_state["errors"].items()):
                last_seen = (
                    self._parse_timestamp(error_state.get("last_seen")) if isinstance(error_state, dict) else None
                )
                if last_seen is None or last_seen < cutoff:
                    del file_state["errors"][signature]
            if not file_state["errors"]:
                del cache[key]

    def __init__(self):
        self._bot = Bot()

    def handle(self, *args, **options):
        logger.info("start")
        current_time = timezone.now()
        cache_filepath = os.path.join("./logs/cache.yaml")
        if os.path.exists(cache_filepath):
            with open(cache_filepath) as fo:
                cache = yaml.safe_load(fo) or {}
        else:
            cache = {}
        check_logs_cache = cache.setdefault("check_logs", {})

        self._check(
            "./logs/legacy/update.log",
            cache=check_logs_cache,
            key="legacy/update.log",
            extractor=self._extract_php_errors,
            require_complete=True,
            current_time=current_time,
        )

        files = []
        files.extend(glob.glob("./logs/*/**/*.log", recursive=True))
        for log_file in files:
            if log_file.endswith("check_logs.log"):
                continue
            if "/legacy/removed/" in log_file:
                continue
            key = os.path.relpath(log_file, "logs")
            if key == "legacy/update.log":
                continue
            regex = r"^[^-\{\+\!\n]*\b(error\b|exception\b[^\(]).*$"
            self._check(
                log_file,
                regex=regex,
                cache=check_logs_cache,
                key=key,
                current_time=current_time,
            )

        self._cleanup_error_cache(check_logs_cache, current_time)

        cache = yaml.dump(cache, default_flow_style=False)
        with open(cache_filepath, "w") as fo:
            fo.write(cache)
        logger.info("end")
