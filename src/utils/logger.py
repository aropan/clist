import contextlib
import logging
import time


@contextlib.contextmanager
def suppress_db_logging_context():
    logger = logging.getLogger('django.db.backends')
    level = logger.getEffectiveLevel()
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(level)


@contextlib.contextmanager
def measure_time(name, logger=logging):
    start = time.time()
    try:
        logger.info('%s started', name)
        yield
    finally:
        logger.info('%s finished in %.3f seconds', name, time.time() - start)


class NullLogger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def nothing(*args, **kwargs):
        pass

    def __getattr__(self, name):
        return self.nothing
