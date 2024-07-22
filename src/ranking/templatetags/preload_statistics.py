from collections import defaultdict

from django import template
from django.db.models import Q

from ranking.models import Account

register = template.Library()


@register.simple_tag
def preload_statistics(instances, base_resource, attr=None):
    ret = {}
    members = defaultdict(list)
    for instance in instances:
        statistics = getattr(instance, attr, []) if attr else [instance]
        for statistic in statistics:
            if '_members' in statistic.addition:
                for member in statistic.addition['_members']:
                    if not member or 'account' not in member:
                        continue
                    if 'resource' in member:
                        resource = member['resource']
                    elif isinstance(base_resource, str):
                        resource = getattr(instance, base_resource)
                    else:
                        resource = base_resource.id
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
