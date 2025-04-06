#!/usr/bin/env python3

import colorsys
import logging
import re
from copy import deepcopy

import cssutils
from stringcolor import cs

from clist.models import Resource
from utils.strings import print_diff


def run(host=None, *args):
    cssutils.log.setLevel(logging.CRITICAL)
    sheet = cssutils.parseFile('static/css/base.css')

    selector_coloring = {}
    for rule in sheet:
        if hasattr(rule, 'selectorText'):
            selector = rule.selectorText.lstrip('.')
            color = rule.style.getPropertyValue('color')
            if color and re.match('#[0-9A-Za-z]', color):
                color = color.lstrip('#')
                if len(color) == 3:
                    color = ''.join(a + b for a, b in zip(color, color))
                color = '#' + color
                assert selector not in selector_coloring or selector_coloring.get(selector) == color
                selector_coloring[selector] = color

    resources = Resource.objects.all()
    if host:
        resources = resources.filter(host__regex=host)
    print(f'Found {resources.count()} resources: {resources.values_list("host", flat=True)}')

    for resource in resources:
        if not resource.ratings:
            continue
        orig_ratings = deepcopy(resource.ratings)
        to_save = False
        prev_rgb = None
        hsl = None
        for rating in resource.ratings:
            cls = f'coder-{rating["color"]}'
            if 'rgb' in rating:
                rating.pop('rgb')
            if 'hsv' in rating:
                rating.pop('hsv')
            hex_rgb = selector_coloring[cls]
            if rating.get('hex_rgb') != hex_rgb:
                rating['hex_rgb'] = hex_rgb
                to_save = True

            rgb = [int(hex_rgb[i:i + 2], 16) / 255 for i in range(1, 6, 2)]
            H, L, S = [round(x, 2) for x in colorsys.rgb_to_hls(*rgb)]

            if prev_rgb == hex_rgb:
                H, S, L = hsl
                L *= 0.75
            hsl = [H, S, L]
            if rating.get('hsl') != hsl:
                rating['hsl'] = hsl
                to_save = True
            prev_rgb = hex_rgb

        limit = None
        next_rating = resource.ratings[-1]
        for rating in reversed(resource.ratings[:-1]):
            next_rating_value = next_rating['low']
            if rating.get('high') != next_rating_value:
                rating['high'] = next_rating_value
                to_save = True
            if limit is None or rating['hex_rgb'] != limit['hex_rgb']:
                limit = rating
            if 'high' in limit:
                value = limit['high']
                if rating.get('next') != value:
                    rating['next'] = value
                    to_save = True
            next_rating = rating

        limit = None
        for rating in resource.ratings[1:]:
            if limit is None or rating['hex_rgb'] != limit['hex_rgb']:
                limit = rating
            value = limit['low']
            if rating.get('prev') != value:
                rating['prev'] = value
                to_save = True

        if to_save:
            print()
            print(cs(resource.host, 'cyan'))
            print_diff(orig_ratings, resource.ratings)
            resource.save(update_fields=['ratings'])
