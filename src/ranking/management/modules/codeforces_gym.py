# -*- coding: utf-8 -*-

from ranking.management.modules import codeforces


class Statistic(codeforces.Statistic):

    @staticmethod
    def get_users_infos(*args, **kwargs):
        return []
