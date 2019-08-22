# -*- coding: utf-8 -*-

import os

from common import BaseModule
import yandex
# import opencup


class Statistic(BaseModule):
    def __init__(self, **kwargs):
        standings_url = kwargs.get('standings_url')
        if not standings_url or 'yandex' in standings_url:
            self.module = yandex.Statistic(**kwargs)
        # else:
        #     start_time = kwargs['start_time']
        #     year = start_time.year - 1 + (start_time.month + 3) // 12
        #     season = f'{year}-{year + 1}'
        #     self.module = opencup.Statistic(**kwargs)

    def get_standings(self, users=None):
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

    contest = Contest.objects.filter(host='contests.snarknews.info', end_time__lte=now()).last()

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
