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
