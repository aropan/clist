#!/usr/bin/env python3

import json
from collections.abc import Iterable

import arrow
from django.conf import settings
from django.template.loader import get_template
from django.urls import reverse
from feedgen.feed import FeedGenerator
from tastypie.serializers import Serializer


def use_in_atom_format(bundle, *args, **kwargs):
    return bundle.request.GET.get('format') in ['atom', 'rss']


def reverse_url(name):
    return settings.HTTPS_HOST_ + reverse(name)


class ContestAtomSerializer(Serializer):
    formats = Serializer.formats + ['rss', 'atom']

    content_types = dict(
        list(Serializer.content_types.items()) +
        [
            ('atom', 'application/atom+xml'),
            ('rss', 'application/rss+xml'),
        ]
    )

    def generate_feed(self, data, options=None):
        options = options or {}
        data = self.to_simple(data, options)
        fg = FeedGenerator()
        fg.id(str(hash(json.dumps(data.get('meta', data), sort_keys=True))))
        fg.link(href=reverse_url('clist:main'))
        fg.title('CLIST Feed')
        fg.description('Events of competitive programming')
        fg.icon(reverse_url('favicon'))
        fg.logo(reverse_url('favicon'))
        name, email = settings.ADMINS[0]
        fg.author(name=name, email=email)
        if isinstance(data.get('objects'), Iterable):
            template = get_template('tastypie_swagger/atom_content.html')
            for contest in data['objects']:
                resource = contest['releated_resource']
                fe = fg.add_entry()
                fe.guid(str(contest['id']))
                fe.title(str(contest['event']))
                fe.link(href=contest['href'])
                fe.author(name=resource['name'], uri=resource['url'])
                fe.source(title=resource['name'], url=resource['url'])
                fe.updated(str(arrow.get(contest['updated'])))
                fe.published(str(arrow.get(contest['start_time'])))
                fe.content(template.render({
                    'contest': contest,
                    'resource': resource,
                    'host': settings.HTTPS_HOST_
                }))
        else:
            fg.description(json.dumps(data))
        return fg

    def to_atom(self, *args, **kwargs):
        fg = self.generate_feed(*args, **kwargs)
        return fg.atom_str(pretty=True)

    def to_rss(self, *args, **kwargs):
        fg = self.generate_feed(*args, **kwargs)
        return fg.rss_str(pretty=True)
