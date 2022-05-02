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
