# -*- coding: utf-8 -*-

from clist.models import Resource
from ranking.management.modules import codeforces


class Statistic(codeforces.Statistic):

    @staticmethod
    def get_users_infos(users, resource, accounts, *args, pbar=None, **kwargs):
        original_resource = Resource.get('cf')

        keys = [account.key for account in accounts if not account.info.get('is_ghost')]
        renamings = {r.old_key: r.new_key for r in original_resource.accountrenaming_set.filter(old_key__in=keys)}

        for user in users:
            if pbar:
                pbar.update()
            data = {'rename': renamings[user]} if user in renamings else {'skip': True}
            yield data
