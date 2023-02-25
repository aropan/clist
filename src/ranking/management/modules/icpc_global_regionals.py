#!/usr/bin/env python3


from ranking.management.modules import icpc_baylor


class Statistic(icpc_baylor.Statistic):

    def __init__(self, **kwargs):
        kwargs['is_regional'] = True
        super().__init__(**kwargs)
