#!/usr/bin/env python3


from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.aggregates import ArrayAgg
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import ExpressionWrapper, OuterRef, Q, Subquery
from sql_util.utils import Exists
from tastypie import fields

from clist.api import v3
from clist.api.v3 import (BaseModelResource, ContestResource, ResourceResource, StatisticsResource,  # noqa
                          use_for_is_real, use_for_is_virtual, use_in_detail_only, use_in_me_only)
from clist.models import Contest, Problem, ProblemVerdict
from favorites.models import Activity
from true_coders.models import CoderProblem


class AccountResource(v3.AccountResource):
    resource = fields.CharField('resource__host')
    resource_id = fields.IntegerField('resource_id')
    handle = fields.CharField('key')
    name = fields.CharField('name', null=True)
    rating = fields.IntegerField('rating', null=True)
    resource_rank = fields.IntegerField('resource_rank', null=True)
    n_contests = fields.IntegerField('n_contests')
    last_activity = fields.DateTimeField('last_activity', null=True)
    total_count = fields.BooleanField()

    class Meta(v3.AccountResource.Meta):
        filtering = {
            'total_count': ['exact'],
            'id': ['exact', 'in'],
            'resource_id': ['exact', 'in'],
            'resource': ['exact', 'regex', 'iregex', 'in'],
            'handle': ['exact', 'in'],
            'rating': ['exact', 'gt', 'lt', 'gte', 'lte', 'isnull'],
            'resource_rank': ['exact', 'gt', 'lt', 'gte', 'lte', 'isnull'],
            'last_activity': ['exact', 'gt', 'lt', 'gte', 'lte', 'week_day'],
        }
        ordering = ['id', 'handle', 'rating', 'resource_rank', 'n_contests', 'last_activity']


class CoderResource(v3.CoderResource):
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

    class Meta(v3.CoderResource.Meta):
        pass


class ProblemResource(BaseModelResource):
    name = fields.CharField('name')
    contest_ids = fields.ListField('contest_ids', null=True,
                                   help_text="A list of data. Ex: {'abc', 26.73, 8}")
    divisions = fields.ListField('divisions', null=True)
    kinds = fields.ListField('kinds', null=True)
    resource = fields.CharField('resource__host')
    resource_id = fields.IntegerField('resource_id')
    slug = fields.CharField('slug', null=True)
    short = fields.CharField('short', null=True)
    url = fields.CharField('url', null=True)
    archive_url = fields.CharField('archive_url', null=True)
    n_attempts = fields.IntegerField('n_attempts', null=True)
    n_accepted = fields.IntegerField('n_accepted', null=True)
    n_partial = fields.IntegerField('n_partial', null=True)
    n_hidden = fields.IntegerField('n_hidden', null=True)
    n_total = fields.IntegerField('n_total', null=True)
    rating = fields.IntegerField('rating', null=True, help_text='Resource rating')
    favorite = fields.BooleanField('is_favorite', null=True, help_text='User-marked as favorite')
    note = fields.CharField('note_text', null=True, help_text='User-specified note')
    solved = fields.BooleanField('solved', help_text='Solved in resource system or user-marked as solved')
    reject = fields.BooleanField('reject', help_text='Rejected in resource system or user-marked as reject')
    system_solved = fields.BooleanField('system_solved', help_text='Solved in resource system')
    system_reject = fields.BooleanField('system_reject', help_text='Rejected in resource system')
    user_solved = fields.BooleanField('user_solved', help_text='User-marked as solved')
    user_todo = fields.BooleanField('user_todo', help_text='User-marked as todo')
    user_reject = fields.BooleanField('user_reject', help_text='User-marked as reject')
    total_count = fields.BooleanField()

    class Meta(BaseModelResource.Meta):
        abstract = False
        queryset = Problem.objects.all()
        excludes = ('total_count', 'solved', 'reject')
        filtering = {
            'total_count': ['exact'],
            'name': ['exact', 'in'],
            'contest_ids': ['exact', 'contains'],
            'resource': ['exact', 'iregex', 'regex', 'in'],
            'resource_id': ['exact', 'in'],
            'slug': ['exact', 'in'],
            'short': ['exact', 'in'],
            'url': ['exact', 'regex'],
            'archive_url': ['exact', 'regex'],
            'n_attempts': ['exact', 'gt', 'lt', 'gte', 'lte'],
            'n_accepted': ['exact', 'gt', 'lt', 'gte', 'lte'],
            'n_partial': ['exact', 'gt', 'lt', 'gte', 'lte'],
            'n_hidden': ['exact', 'gt', 'lt', 'gte', 'lte'],
            'n_total': ['exact', 'gt', 'lt', 'gte', 'lte'],
            'rating': ['exact', 'gt', 'lt', 'gte', 'lte'],
            'favorite': ['exact'],
            'note': ['exact', 'in'],
            'solved': ['exact'],
            'reject': ['exact'],
            'system_solved': ['exact'],
            'system_reject': ['exact'],
            'user_solved': ['exact'],
            'user_todo': ['exact'],
            'user_reject': ['exact'],
        }
        ordering = ['id', 'name', 'slug', 'short', 'url', 'archive_url',
                    'n_attempts', 'n_accepted', 'n_partial', 'n_hidden', 'n_total', 'rating']

    def get_object_list(self, request):
        problems = super().get_object_list(request)
        problems = problems.annotate_favorite(request.user)
        problems = problems.annotate_note(request.user)
        problems = problems.select_related('resource')

        contests = Contest.objects.filter(problem_set__id=OuterRef('pk'))
        contests = contests.values('problem_set__id').annotate(ids=ArrayAgg('id')).values('ids')
        problems = problems.annotate(contest_ids=Subquery(contests, output_field=ArrayField(models.IntegerField())))

        content_type = ContentType.objects.get_for_model(Problem)
        coder = request.user.coder if request.user.is_authenticated else None
        activities = Activity.objects.filter(coder=coder, content_type=content_type, object_id=OuterRef('pk'))
        problems = problems.annotate(user_todo=Exists(activities.filter(activity_type=Activity.Type.TODO)))
        problems = problems.annotate(user_solved=Exists(activities.filter(activity_type=Activity.Type.SOLVED)))
        problems = problems.annotate(user_reject=Exists(activities.filter(activity_type=Activity.Type.REJECT)))

        coder_problems = CoderProblem.objects.filter(coder=coder, problem=OuterRef('pk'))
        problems = problems.annotate(system_solved=Exists(coder_problems.filter(verdict=ProblemVerdict.SOLVED)))
        problems = problems.annotate(system_reject=Exists(coder_problems.filter(verdict=ProblemVerdict.REJECT)))

        problems = problems.annotate(solved=ExpressionWrapper(Q(system_solved=True) | Q(user_solved=True),
                                                              output_field=models.BooleanField()))
        problems = problems.annotate(reject=ExpressionWrapper(Q(system_reject=True) | Q(user_reject=True),
                                                              output_field=models.BooleanField()))

        return problems
