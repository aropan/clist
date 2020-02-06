import re


def verify_regex(regex):
    try:
        re.compile(regex)
    except Exception:
        regex = re.sub(r'([\{\}\[\]\(\)\\\*])', r'\\\1', regex)
    return regex
