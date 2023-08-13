import os
import sys


def is_interactive():
    return os.isatty(sys.stdout.fileno())
