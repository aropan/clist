import logging
import re
import sys
import unittest

from django.test.runner import DiscoverRunner
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

MAX_CAPTURE_LINES = 30
MAX_TRACEBACK_LINES = 40
MAX_LINE_LENGTH = 500

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
NOISY_CAPTURE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} .* \[cache\] ")


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

    def get_resultclass(self):
        resultclass = super().get_resultclass()
        if resultclass is None and self.verbosity == 1:
            return CompactTestResult
        return resultclass
