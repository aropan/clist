# -*- coding: utf-8 -*-

import os
from urllib.parse import urlparse

from ranking.management.modules.common import BaseModule
from ranking.management.modules import yandex, opencup


class Statistic(BaseModule):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        host = urlparse(self.standings_url).netloc
        if not host or 'yandex' in host:
            self.module = yandex.Statistic(**kwargs)
        else:
            self.module = opencup.Statistic(**kwargs)

    def get_standings(self, users=None, statistics=None):
        return self.module.get_standings(users)


if __name__ == "__main__":
    from pprint import pprint
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'pyclist.settings'

    from django import setup
    setup()

    from clist.models import Contest
    from django.utils.timezone import now

    contests = Contest.objects.filter(host='contests.snarknews.info', end_time__lte=now())
    contests = contests.filter(title='1 раунд. SnarkNews Winter Series - 2020')

    contest = contests.last()

    statistic = Statistic(
        name=contest.title,
        url=contest.url,
        key=contest.key,
        standings_url=contest.standings_url,
        start_time=contest.start_time,
    )
    s = statistic.get_standings()
    # pprint(s['result'])
    pprint(s['problems'])
    pprint(s['result']['Ildar Gainullin 2019-2020'])
