# Keep the long-standing utils.is_interactive import path.
# ruff: file-ignore[non-empty-init-module]
import sys


def is_interactive():
    return sys.stdout.isatty()
