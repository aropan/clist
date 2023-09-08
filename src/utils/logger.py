import contextlib
import logging


@contextlib.contextmanager
def suppress_db_logging_context():
    logger = logging.getLogger('django.db.backends')
    level = logger.getEffectiveLevel()
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(level)
