import ipaddress
import logging
import os
import re
import socket
import sys
import unittest
from pathlib import PurePath
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management import CommandError
from django.test.runner import DiscoverRunner
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

MAX_CAPTURE_LINES = 30
MAX_TRACEBACK_LINES = 40
MAX_LINE_LENGTH = 500
MAX_NETWORK_VIOLATION_LINES = 50

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
NOISY_CAPTURE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} .* \[cache\] ")

LOOPBACK_HOSTS = frozenset({"localhost", "ip6-localhost", "ip6-loopback"})
NETWORK_CLIENT_COMMANDS = frozenset({"curl", "wget"})
HOST_LOOKUP_EVENTS = frozenset({
    "socket.getaddrinfo",
    "socket.gethostbyaddr",
    "socket.gethostbyname",
    "socket.gethostbyname_ex",
})
NETWORK_AUDIT_EVENTS = HOST_LOOKUP_EVENTS | {"socket.connect", "subprocess.Popen"}


class NetworkAccessDenied(RuntimeError):
    pass


def _url_host(value):
    return urlsplit(value).hostname if "://" in value else value


def network_hosts_from_settings(databases, caches, rq_queues, channel_layers):
    hosts = {database.get("HOST") for database in databases.values()}
    for cache in caches.values():
        locations = cache.get("LOCATION") or []
        if isinstance(locations, str):
            locations = locations.split(",")
        hosts.update(_url_host(location.strip()) for location in locations)
    for queue in rq_queues.values():
        hosts.add(queue.get("HOST"))
        if queue.get("URL"):
            hosts.add(_url_host(queue["URL"]))
    for layer in channel_layers.values():
        for host in layer.get("CONFIG", {}).get("hosts", []):
            if isinstance(host, dict):
                hosts.add(host.get("host") or _url_host(host.get("address", "")))
            elif isinstance(host, (list, tuple)):
                hosts.add(host[0])
            else:
                hosts.add(_url_host(host))
    return {host.lower() for host in hosts if host and not host.startswith("/")}


def network_allowlist(hosts):
    hostname = socket.gethostname()
    allowed = {hostname.lower(), socket.getfqdn(hostname).lower()}
    for host in {*hosts, hostname}:
        allowed.add(host.lower())
        try:
            addresses = socket.getaddrinfo(host, None)
        except OSError:
            continue
        allowed.update(address[4][0].lower() for address in addresses)
    return frozenset(allowed)


def _is_allowed_host(host, allowed_hosts):
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not host:
        return True
    host = str(host).lower().rstrip(".")
    if host in LOOPBACK_HOSTS or host in allowed_hosts:
        return True
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_loopback or address.is_unspecified or str(address) in allowed_hosts


def network_violation(event, args, allowed_hosts):
    """Return the denied network target of an audit event, or None when the event is allowed."""
    if event in HOST_LOOKUP_EVENTS:
        host = args[0]
        return None if _is_allowed_host(host, allowed_hosts) else str(host)
    if event == "socket.connect":
        sock, address = args
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return None
        return None if _is_allowed_host(address[0], allowed_hosts) else f"{address[0]}:{address[1]}"
    if event == "subprocess.Popen":
        executable, popen_args = args[0], args[1]
        if executable is None:
            executable = popen_args[0] if isinstance(popen_args, (list, tuple)) else popen_args
        command = PurePath(os.fsdecode(executable)).name
        return command if command in NETWORK_CLIENT_COMMANDS else None
    return None


def _current_test_id():
    frame = sys._getframe(1)
    while frame is not None:
        candidate = frame.f_locals.get("self")
        if isinstance(candidate, unittest.TestCase):
            return candidate.id()
        frame = frame.f_back
    return None


class NetworkGuard:
    def __init__(self, allowed_hosts):
        self.allowed_hosts = frozenset(allowed_hosts)
        self.active = False
        self.violations = []
        self._installed = False

    def install(self):
        # Audit hooks cannot be removed, so an installed guard is disabled through `active`.
        if not self._installed:
            sys.addaudithook(self.audit)
            self._installed = True

    def audit(self, event, args):
        if not self.active or event not in NETWORK_AUDIT_EVENTS:
            return
        target = network_violation(event, args, self.allowed_hosts)
        if target is None:
            return
        self.violations.append((_current_test_id(), event, target))
        raise NetworkAccessDenied(f"network access is denied during tests: {event} {target}")

    def report(self, stream):
        violations = list(dict.fromkeys(self.violations))
        print(f"\nNetwork access denied {len(self.violations)} time(s) during tests:", file=stream)
        for test_id, event, target in violations[:MAX_NETWORK_VIOLATION_LINES]:
            print(f"  {test_id or '<outside a test>'}: {event} {target}", file=stream)
        if len(violations) > MAX_NETWORK_VIOLATION_LINES:
            print(f"  ... {len(violations) - MAX_NETWORK_VIOLATION_LINES} more unique violation(s)", file=stream)


def _count_test_cases(suite):
    subsuites = getattr(suite, "subsuites", None)
    if subsuites is not None:
        return sum(subsuite.countTestCases() for subsuite in subsuites)
    return suite.countTestCases()


def _compact_text(text, *, max_lines, tail_only=False, drop_noisy=False):
    lines = ANSI_ESCAPE_RE.sub("", text.replace("\r", "\n")).splitlines()
    noisy_lines = 0
    if drop_noisy:
        noisy_lines = sum(bool(NOISY_CAPTURE_RE.match(line)) for line in lines)
        lines = [line for line in lines if not NOISY_CAPTURE_RE.match(line)]

    omitted_lines = max(0, len(lines) - max_lines)
    if omitted_lines:
        omission = f"... {omitted_lines} earlier line(s) omitted ..."
        if tail_only:
            lines = [omission, *lines[-max_lines:]]
        else:
            head_count = max_lines // 2
            lines = [*lines[:head_count], omission, *lines[-(max_lines - head_count) :]]
    if noisy_lines:
        lines.insert(0, f"... {noisy_lines} cache line(s) omitted ...")

    compacted = []
    for line in lines:
        if len(line) > MAX_LINE_LENGTH:
            omitted_characters = len(line) - MAX_LINE_LENGTH
            line = f"{line[:MAX_LINE_LENGTH]}... <{omitted_characters} character(s) omitted>"
        compacted.append(line)
    return "\n".join(compacted)


def _console_logging_handlers():
    loggers = [logging.getLogger()]
    loggers.extend(
        logger for logger in logging.Logger.manager.loggerDict.values() if isinstance(logger, logging.Logger)
    )

    handlers = {}
    for logger in loggers:
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                handlers[id(handler)] = handler
    return handlers.values()


class CompactTestResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.dots = False
        self.showAll = False
        self.total_tests = 0
        self._logging_streams = []
        self._progress = None
        self._progress_task = None

    def startTestRun(self):
        super().startTestRun()
        console = Console(file=self.stream, highlight=False)
        if self.total_tests and console.is_terminal:
            self._progress = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
                auto_refresh=False,
            )
            self._progress.start()
            self._progress_task = self._progress.add_task("Tests", total=self.total_tests)
            self._progress.refresh()

    def stopTestRun(self):
        if self._progress is not None:
            self._progress.stop()
        super().stopTestRun()

    def startTest(self, test):
        super().startTest(test)
        if self.buffer:
            self._logging_streams = []
            for handler in _console_logging_handlers():
                self._logging_streams.append((handler, handler.stream))
                handler.setStream(sys.stderr)

    def stopTest(self, test):
        for handler, stream in reversed(self._logging_streams):
            handler.setStream(stream)
        self._logging_streams = []
        super().stopTest(test)

        if self._progress is not None:
            failed = len(self.failures) + len(self.errors) + len(self.unexpectedSuccesses)
            description = "Tests" if not failed else f"Tests [red]({failed} failed)[/red]"
            self._progress.update(self._progress_task, advance=1, description=description, refresh=True)

    def _exc_info_to_string(self, err, test):
        buffered = self.buffer
        self.buffer = False
        try:
            traceback_text = super()._exc_info_to_string(err, test)
        finally:
            self.buffer = buffered

        sections = [_compact_text(traceback_text, max_lines=MAX_TRACEBACK_LINES)]
        if buffered:
            for label, output in (("stdout", sys.stdout.getvalue()), ("stderr", sys.stderr.getvalue())):
                if output:
                    context = _compact_text(output, max_lines=MAX_CAPTURE_LINES, tail_only=True, drop_noisy=True)
                    sections.append(f"Captured {label} (tail):\n{context}")
        return "\n\n".join(section.rstrip() for section in sections if section)

    def addError(self, test, err):
        super().addError(test, err)
        self._mirrorOutput = False

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._mirrorOutput = False

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._mirrorOutput = False


class CompactTextTestRunner(unittest.TextTestRunner):
    def run(self, test):
        self.total_tests = test.countTestCases()
        return super().run(test)

    def _makeResult(self):
        result = super()._makeResult()
        if isinstance(result, CompactTestResult):
            result.total_tests = self.total_tests
        return result


class CompactTestRunner(DiscoverRunner):
    test_runner = CompactTextTestRunner

    def __init__(self, *args, require_tests=False, deny_network=False, **kwargs):
        super().__init__(*args, **kwargs)
        # The audit hook lives in this process only: spawned workers run unguarded and forked ones lose records.
        if deny_network and self.parallel > 1:
            raise CommandError("You cannot use --deny-network with parallel tests; pass --parallel=1 to use it.")
        self.require_tests = require_tests
        self.deny_network = deny_network
        self.network_guard = None

    @classmethod
    def add_arguments(cls, parser):
        super().add_arguments(parser)
        parser.set_defaults(buffer=True)
        parser.add_argument(
            "--no-buffer",
            action="store_false",
            dest="buffer",
            help="Show stdout, stderr, and logs from every test.",
        )
        parser.add_argument(
            "--require-tests",
            action="store_true",
            help="Fail when a test label, or the whole selection, contains no tests.",
        )
        parser.add_argument(
            "--deny-network",
            action="store_true",
            help=(
                "Fail the run when tests resolve or connect to a host other than loopback and the configured "
                "database, cache, queue, and channel layer hosts, or start curl/wget."
            ),
        )

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        if self.deny_network:
            hosts = network_hosts_from_settings(
                settings.DATABASES,
                settings.CACHES,
                getattr(settings, "RQ_QUEUES", {}),
                getattr(settings, "CHANNEL_LAYERS", {}),
            )
            self.network_guard = NetworkGuard(network_allowlist(hosts))
            self.network_guard.install()
            self.network_guard.active = True

    def teardown_test_environment(self, **kwargs):
        if self.network_guard is not None:
            self.network_guard.active = False
        super().teardown_test_environment(**kwargs)

    def load_tests_for_label(self, label, discover_kwargs):
        tests = super().load_tests_for_label(label, discover_kwargs)
        if self.require_tests and (tests is None or not tests.countTestCases()):
            raise CommandError(f"Test label {label!r} selected no tests.")
        return tests

    def build_suite(self, test_labels=None, **kwargs):
        suite = super().build_suite(test_labels, **kwargs)
        if self.require_tests and not _count_test_cases(suite):
            raise CommandError("The selected test labels and filters contain no tests.")
        return suite

    def suite_result(self, suite, result, **kwargs):
        failures = super().suite_result(suite, result, **kwargs)
        if self.network_guard is not None and self.network_guard.violations:
            self.network_guard.report(sys.stderr)
            failures += len(self.network_guard.violations)
        return failures

    def get_resultclass(self):
        resultclass = super().get_resultclass()
        if resultclass is None and self.verbosity == 1:
            return CompactTestResult
        return resultclass
