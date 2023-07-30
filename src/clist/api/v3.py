#!/usr/bin/env python3


from django.urls import re_path
from django.urls import reverse
from tastypie import fields
from tastypie.utils import trailing_slash

from clist.api.common import is_true_value
from clist.api.v2 import (AccountResource, BaseModelResource, ContestResource, ResourceResource,  # noqa: F401
                          StatisticsResource)
from true_coders.models import Coder


def use_in_me_only(bundle, *args, **kwargs):
    url = reverse('clist:api:v3:api_dispatch_me', kwargs={'api_name': 'v3', 'resource_name': 'coder'})
    return url == bundle.request.path


def use_in_detail_only(bundle, *args, **kwargs):
    with_accounts = is_true_value(bundle.request.GET.get('with_accounts'))
    query_by_id = bool(bundle.request.GET.get('id') or bundle.request.GET.get('handle'))
    url = reverse('clist:api:v3:api_dispatch_list', kwargs={'api_name': 'v3', 'resource_name': 'coder'})
    return with_accounts or query_by_id or not (url == bundle.request.path or use_in_me_only(bundle, *args, **kwargs))


def use_for_is_real(bundle, *args, **kwargs):
    return not bundle.data['is_virtual']


def use_for_is_virtual(bundle, *args, **kwargs):
    return bundle.data['is_virtual']


class CoderResource(BaseModelResource):
    handle = fields.CharField('username')
    is_virtual = fields.BooleanField('is_virtual')
    first_name = fields.CharField('user__first_name', null=True, use_in=use_for_is_real,
                                  help_text='Unicode string data. Ex: "Hello World". '
                                  'Field is available only if coder is real')
    last_name = fields.CharField('user__last_name', null=True, use_in=use_for_is_real,
                                 help_text='Unicode string data. Ex: "Hello World". '
                                 'Field is available only if coder is real')
    country = fields.CharField('country')
    timezone = fields.CharField('timezone', use_in=use_in_me_only)
    email = fields.CharField('user__email', use_in=use_in_me_only, null=True)
    n_accounts = fields.IntegerField('n_accounts', use_in='list')
    display_name = fields.CharField('display_name', use_in=use_for_is_virtual,
                                    help_text='Unicode string data. Ex: "Hello World". '
                                    'Field is available only if coder is virtual')
    accounts = fields.ManyToManyField(AccountResource, 'account_set', use_in=use_in_detail_only, full=True)
    with_accounts = fields.BooleanField()
    total_count = fields.BooleanField()

    class Meta(BaseModelResource.Meta):
        abstract = False
        object_class = Coder
        queryset = Coder.objects.all()
        resource_name = 'coder'
        excludes = ('total_count', 'with_accounts')
        filtering = {
            'total_count': ['exact'],
            'with_accounts': ['exact'],
            'country': ['exact'],
            'id': ['exact', 'in'],
            'handle': ['exact', 'iregex', 'regex', 'in'],
            'is_virtual': ['exact'],
        }
        extra_actions = [
            {
                'name': 'me',
                'summary': 'Retrieve your coder',
                'resource_type': 'list',
                'responseClass': 'coder',
            }
        ]
        ordering = ['n_accounts']

    def me(self, request, *args, **kwargs):
        kwargs['me'] = True
        return self.dispatch('detail', request, **kwargs)

    def prepend_urls(self):
        return [
            re_path(
                r'^(?P<resource_name>%s)/me%s$' % (self._meta.resource_name, trailing_slash),
                self.wrap_view('me'),
                name='api_dispatch_me'
            )
        ]

    def dehydrate(self, *args, **kwargs):
        bundle = super().dehydrate(*args, **kwargs)
        for k in self.fields.keys():
            if k in bundle.data and not bundle.data[k] and isinstance(bundle.data[k], str):
                bundle.data[k] = None
        bundle.data.pop('with_accounts', None)
        return bundle

    def build_filters(self, filters=None, *args, **kwargs):
        filters = filters or {}
        me = filters.pop('me', None)
        filters.pop('with_accounts', None)
        filters = super().build_filters(filters, *args, **kwargs)
        filters['me'] = me
        return filters

    def apply_filters(self, request, applicable_filters):
        me = applicable_filters.pop('me', None)
        qs = super().apply_filters(request, applicable_filters)
        if me:
            qs = qs.filter(pk=request.user.coder.pk)
        qs = qs.select_related('user')

        fake_bundle = type('obj', (object,), {'request': request})
        if use_in_detail_only(fake_bundle):
            qs = qs.prefetch_related('account_set__resource')
        return qs
