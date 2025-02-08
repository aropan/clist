#!/usr/bin/env python3


def localize_data(data, locale):
    if (
        isinstance(data, dict)
        and (translation := data.get('translation'))
        and locale in translation
    ):
        data.update(translation[locale])
    return data
