from collections import defaultdict

from django import template

from ranking.models import Account

register = template.Library()


@register.simple_tag
def preload_statistics(statistics, resource):
    ret = {}
    members = []
    for s in statistics:
        if '_members' in s.addition:
            members.extend([m['account'] for m in s.addition['_members']])
    if members:
        qs = Account.objects.filter(resource=resource, key__in=set(members))
        ret['accounts'] = defaultdict(dict)
        ret['accounts'].update({a.key: a for a in qs})
    else:
        ret['accounts'] = {}
    return ret
