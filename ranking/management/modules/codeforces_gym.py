# -*- coding: utf-8 -*-

from pprint import pprint
from . import codeforces


class Statistic(codeforces.Statistic):
    pass


if __name__ == '__main__':
    # s = Statistic(url='http://codeforces.com/gym/100548/standings', key='100548')
    # pprint(s.get_standings(['Vladik']))
    s = Statistic(url='codeforces.com/gym/100548', key='100548')
    pprint(s.get_standings(['Tigerrrrr']))
