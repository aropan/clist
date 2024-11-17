import random
import secrets
import string
from collections import Counter

from bs4 import BeautifulSoup
from markdown import markdown


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
