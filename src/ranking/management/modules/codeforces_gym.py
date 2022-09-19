# -*- coding: utf-8 -*-

from pprint import pprint

from ranking.management.modules import codeforces


class Statistic(codeforces.Statistic):

    @staticmethod
    def get_users_infos(*args, **kwargs):
        return []


if __name__ == '__main__':
    # s = Statistic(url='http://codeforces.com/gym/100548/standings', key='100548')
    # pprint(s.get_standings(['Vladik']))
    s = Statistic(url='codeforces.com/gym/100548', key='100548')
    pprint(s.get_standings(['tgrfz']))
