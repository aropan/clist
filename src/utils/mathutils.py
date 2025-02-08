#!/usr/bin/env python3

import math


def get_divisors(n, reverse=False):
    if reverse:
        for x in get_divisors(n):
            yield n // x
        return

    m = int(math.sqrt(n + 1e-9))
    for i in range(1, m + 1):
        if n % i == 0:
            yield i
    if m * m == n:
        m -= 1
    for i in reversed(range(1, m + 1)):
        if n % i == 0:
            yield n // i


def min_with_none(*args):
    valid_args = [x for x in args if x is not None]
    if not valid_args:
        return None
    return min(valid_args)


def max_with_none(*args):
    valid_args = [x for x in args if x is not None]
    if not valid_args:
        return None
    return max(valid_args)


def sum_with_none(*args):
    if all(x is None for x in args):
        return None
    return sum(x for x in args if x is not None)


def round_sig(number, n_sig_digits):
    n_digits = max(0, n_sig_digits - len(str(int(abs(number)))))
    return round(number, n_digits)


def is_close(a, b):
    if a is None or b is None:
        return a == b
    return math.isclose(a, b)
