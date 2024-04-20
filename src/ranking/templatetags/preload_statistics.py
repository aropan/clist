from collections import defaultdict

from django import template
from django.db.models import Q

from ranking.models import Account

register = template.Library()


@register.simple_tag
def preload_statistics(statistics, base_resource):
    ret = {}
    members = defaultdict(list)
    for s in statistics:
        if '_members' in s.addition:
            for member in s.addition['_members']:
                if not member or 'account' not in member:
                    continue
                resource = member.get('resource', base_resource.id)
                members[resource].append(member['account'])
    if members:
        accounts_filter = Q()
        for resource, members in members.items():
            accounts_filter |= Q(resource_id=resource, key__in=set(members))
        qs = Account.objects.filter(accounts_filter).select_related('resource')
        ret['accounts'] = defaultdict(dict)
        ret['accounts'].update({a.key: a for a in qs})
    else:
        ret['accounts'] = {}
    return ret
