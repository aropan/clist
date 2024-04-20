from collections import Counter


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
