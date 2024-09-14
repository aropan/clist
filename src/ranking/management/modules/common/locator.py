#!/usr/bin/env python3

import logging
import os
import re

import yaml
from filelock import FileLock
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

logging.getLogger('geopy').setLevel(logging.INFO)


class Locator:

    def __init__(
        self,
        locations_file='sharedfiles/locator/data.yaml',
        default_locations=None,
    ):
        self.locations_file = locations_file
        geolocator = Nominatim(user_agent="clist.by", timeout=5)
        self.geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, max_retries=3)
        self.lock = FileLock(os.path.realpath(self.locations_file) + '.lock')
        self.locations = None
        self.default_locations = default_locations

    def get_address(self, location, lang='en'):
        if not location:
            return

        location = re.sub(r'(\bг\.|\bг\b)', '', location)
        location = re.sub(r'<[^>]*>', ' ', location)
        location = re.sub(r'[.,\s]+', ' ', location)
        location = location.strip()

        location_lower = location.lower()
        if self.default_locations and location_lower in self.default_locations:
            location = self.default_locations[location_lower]
            if location is None:
                return

        if self.locations is None or location not in self.locations:
            try:
                location_info = {
                    'en': self.geocode(location, language='en').address,
                    'ru': self.geocode(location, language='ru').address,
                }
            except Exception:
                location_info = None
            if self.locations is not None:
                self.locations[location] = location_info
        else:
            location_info = self.locations[location]

        return location_info[lang] if location_info else None

    def get_country(self, location, lang='en'):
        address = self.get_address(location=location, lang=lang)
        if not address:
            return
        *_, country = map(str.strip, address.split(','))
        if country.startswith('The '):
            country = country[4:]
        return country

    def get_city(self, location, lang='en'):
        address = self.get_address(location=location, lang=lang)
        if not address or ',' not in address:
            return
        city, *_ = map(str.strip, address.split(','))
        return city

    def get_location_dict(self, location, lang='en'):
        ret = {}

        address = self.get_address(location, lang=lang)
        if not address:
            return ret

        country = self.get_country(location, lang=lang)
        if country:
            ret['country'] = country

        city = self.get_city(location, lang=lang)
        if city:
            ret['city'] = city

        return ret

    def read(self):
        with self.lock.acquire(timeout=60):
            self.locations = {}
            if os.path.exists(self.locations_file):
                with open(self.locations_file, 'r') as fo:
                    data = yaml.safe_load(fo) or dict()
                    self.locations = {k: v for k, v in data.items() if v}
            if self.locations is None:
                self.locations = {}

    def write(self):
        if self.locations is not None:
            with self.lock.acquire(timeout=60):
                with open(self.locations_file, 'wb') as fo:
                    yaml.dump(self.locations, fo, encoding='utf8', allow_unicode=True)

    def __enter__(self):
        self.lock.acquire()
        self.read()
        return self

    def __exit__(self, *args, **kwargs):
        self.write()
        self.lock.release()
