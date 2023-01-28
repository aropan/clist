#!/usr/bin/env python3

from traceback_with_variables import ColorSchemes, Format, format_exc

colored_format = Format(color_scheme=ColorSchemes.nice)


def colored_format_exc():
    return format_exc(fmt=colored_format)
