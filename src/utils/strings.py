import random
import re
import secrets
import string
from collections import Counter
from difflib import unified_diff

import yaml
from bs4 import BeautifulSoup
from markdown import markdown
from stringcolor import cs


def trim_on_newline(text, max_length):
    if len(text) <= max_length:
        return text
    pos = text.find('\n', -max_length)
    return text[-max_length:] if pos == -1 else text[pos + 1:]


def string_iou(a, b):
    """
    Compute the intersection over union of two strings via multiset Jaccard similarity.
    """
    a_counter, b_counter = Counter(a), Counter(b)
    intersection = sum((a_counter & b_counter).values())
    union = sum((a_counter | b_counter).values())
    return intersection / union if union > 0 else 0.0


def list_string_iou(a, b):
    intersection = 0
    intersection += sum([max(string_iou(x, y) for y in b) for x in a])
    intersection += sum([max(string_iou(x, y) for y in a) for x in b])
    union = len(a) + len(b)
    return intersection / union if union > 0 else 0.0


def word_string_iou(a, b):
    return list_string_iou(a.split(), b.split())


def slug_string_iou(a, b):
    return list_string_iou(a.split('-'), b.split('-'))


def random_string(length=40):
    return ''.join(random.choices(list(string.ascii_letters + string.digits), k=length))


def generate_secret(length=16):
    return secrets.token_hex(length)


def generate_secret_64():
    return generate_secret(32)


def markdown_to_text(markdown_text):
    return BeautifulSoup(markdown(markdown_text), 'html.parser').get_text()


def markdown_to_html(markdown_text):
    return markdown(markdown_text)


def cut_prefix(text, prefix, strip=True):
    if text.startswith(prefix):
        text = text[len(prefix):]
        if strip:
            text = text.strip()
    return text


def print_diff(p, q):
    if isinstance(p, str):
        p = p.splitlines()
        q = q.splitlines()
    else:
        p = yaml.dump(p, indent=2).splitlines()
        q = yaml.dump(q, indent=2).splitlines()
    for diff in list(unified_diff(p, q)):
        if diff.startswith('+ '):
            print(cs(diff, 'green'))
        elif diff.startswith('- '):
            print(cs(diff, 'red'))
        else:
            print(diff)


def remove_unpaired_surrogates(text):
    result = []
    i, n = 0, len(text)
    while i < n:
        code = ord(text[i])
        if 0xD800 <= code <= 0xDBFF and i + 1 < n and 0xDC00 <= ord(text[i + 1]) <= 0xDFFF:
            result.extend([text[i], text[i + 1]])
            i += 2
        elif 0xD800 <= code <= 0xDBFF or 0xDC00 <= code <= 0xDFFF:
            i += 1
        else:
            result.append(text[i])
            i += 1
    return ''.join(result)


def sanitize_text(text):
    text = re.sub(r'[\x00-\x1F\x7F]', '', text)
    text = remove_unpaired_surrogates(text)
    return text


def sanitize_data(data):
    if isinstance(data, str):
        return sanitize_text(data)
    elif isinstance(data, dict):
        return {sanitize_data(k): sanitize_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_data(x) for x in data]
    elif isinstance(data, tuple):
        return tuple(sanitize_data(x) for x in data)
    else:
        return data
