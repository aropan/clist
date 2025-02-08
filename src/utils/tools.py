#!/usr/bin/env python3


from copy import deepcopy


def sum_data(a, b):
    if a is None or b is None:
        return deepcopy(a if b is None else b)
    if isinstance(a, dict) and isinstance(b, dict):
        ret = deepcopy(a)
        for k, v in b.items():
            if k in ret:
                ret[k] = sum_data(ret[k], v)
            else:
                ret[k] = deepcopy(v)
        return ret
    if isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), 'Lists must have the same length'
        return [sum_data(x, y) for x, y in zip(a, b)]
    if isinstance(a, tuple) and isinstance(b, tuple):
        assert len(a) == len(b), 'Tuples must have the same length'
        return tuple(sum_data(x, y) for x, y in zip(a, b))
    return a + b
