#!/usr/bin/env python3

import re

from strictfire import StrictFire


def pass_args(func, args):
    args = [re.sub('^/', '--', arg) for arg in args]
    StrictFire(func, args)
