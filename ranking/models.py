import re
import collections

import tqdm
from django.db import models, transaction
from django.dispatch import receiver
from django.urls import reverse
from django.contrib.postgres.fields import JSONField
from django_countries.fields import CountryField

from pyclist.models import BaseModel
from true_coders.models import Coder, Party
from clist.models import Contest, Resource
from clist.templatetags.extras import slug


class Account(BaseModel):
    coders = models.ManyToManyField(Coder, blank=True)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    key = models.CharField(max_length=1024, null=False, blank=False)
    name = models.CharField(max_length=1024, null=True, blank=True)
    country = CountryField(null=True, blank=True)
    info = JSONField(default=dict, blank=True)
    updated = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return '%s on %s' % (str(self.key), str(self.resource))

    def dict(self):
        return {
            'account': self.key,
            'resource': self.resource.host,
            'name': self.name,
        }

    def dict_with_info(self):
        ret = self.dict()
        ret.update(self.info.get('profile_url', {}))
        return ret

    class Meta:
        unique_together = ('resource', 'key')


class Rating(BaseModel):
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    party = models.ForeignKey(Party, on_delete=models.CASCADE)

    def __str__(self):
        return 'rating %s by %s' % (str(self.party.name), str(self.contest.title))


class Statistics(BaseModel):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    place = models.CharField(max_length=17, default=None, null=True, blank=True)
    place_as_int = models.IntegerField(default=None, null=True, blank=True)
    solving = models.FloatField(default=0, blank=True)
    upsolving = models.FloatField(default=0, blank=True)
    addition = JSONField(default=dict, blank=True)
    url = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return f'{self.account_id} on {self.contest_id} = {self.solving} + {self.upsolving}'

    class Meta:
        verbose_name_plural = 'Statistics'
        unique_together = ('account', 'contest')

        indexes = [
            models.Index(fields=['place_as_int', '-solving']),
        ]


@receiver(models.signals.pre_save, sender=Statistics)
def statistics_pre_save(sender, instance, *args, **kwargs):
    instance.place_as_int = None
    if instance.place is not None:
        match = re.search('[0-9]+', str(instance.place))
        if match:
            instance.place_as_int = int(match.group(0))


class Module(BaseModel):
    resource = models.OneToOneField(Resource, on_delete=models.CASCADE)
    path = models.CharField(max_length=255)
    min_delay_after_end = models.DurationField()
    max_delay_after_end = models.DurationField()
    delay_on_error = models.DurationField()
    delay_on_success = models.DurationField(null=True, blank=True)
    multi_account_allowed = models.BooleanField(default=False)
    has_accounts_infos_update = models.BooleanField(default=False)

    def __str__(self):
        return '%s: %s' % (self.resource.host, self.path)


class Stage(BaseModel):
    contest = models.OneToOneField(Contest, on_delete=models.CASCADE)
    filter_params = JSONField(default=dict, blank=True)
    score_params = JSONField(default=dict, blank=True)

    def __str__(self):
        return '%s' % (self.contest)

    def update(self):
        stage = self.contest

        contests = Contest.objects.filter(
            resource=self.contest.resource,
            start_time__gte=self.contest.start_time,
            end_time__lte=self.contest.end_time,
            **self.filter_params,
        ).exclude(pk=self.contest.pk)

        contests = contests.order_by('start_time')

        problems_infos = collections.OrderedDict()
        for contest in tqdm.tqdm(contests, desc=f'getting contests for stage {stage}'):
            problems_infos[contest.pk] = {
                'code': str(contest.pk),
                'name': contest.title,
                'url': reverse(
                    'ranking:standings',
                    kwargs={'title_slug': slug(contest.title), 'contest_id': str(contest.pk)}
                ),
                'n_accepted': 0,
                'n_teams': 0,
            }

        statistics = Statistics.objects.filter(contest__in=contests)
        statistics = statistics.select_related('account', 'contest')

        filter_statistics = self.score_params.get('filter_statistics')
        if filter_statistics:
            statistics = statistics.filter(**filter_statistics)

        placing = self.score_params.get('place')
        n_best = self.score_params.get('n_best')

        results = collections.defaultdict(dict)
        for s in tqdm.tqdm(statistics.iterator(), desc=f'getting statistics for stage {stage}'):
            row = results[s.account]
            row['member'] = s.account

            problems_infos[s.contest.pk]['n_teams'] += 1

            status = None
            if s.solving < 1e-9:
                score = 0
            else:
                problems_infos[s.contest.pk]['n_accepted'] += 1
                if placing:
                    placing_ = placing['division'][s.addition['division']] if 'division' in placing else placing
                    score = placing_.get(str(s.place_as_int), placing_['default'])
                    status = s.place_as_int
                else:
                    score = 0

            problems = row.setdefault('problems', {})
            problem = problems.setdefault(str(s.contest.pk), {})
            problem['result'] = score
            url = s.addition.get('url')
            if url:
                problem['url'] = url
            if status is not None:
                problem['status'] = status

            if n_best:
                row.setdefault('scores', []).append((score, problem))
            else:
                row['score'] = row.get('score', 0) + score
            row['points'] = round(row.get('points', 0) + s.solving, 2)

        results = list(results.values())
        if n_best:
            for row in results:
                scores = row.pop('scores')
                for index, (score, problem) in enumerate(sorted(scores, key=lambda s: s[0], reverse=True)):
                    if index < n_best:
                        row['score'] = row.get('score', 0) + score
                    else:
                        problem['status'] = problem.pop('result')

        order_by = self.score_params['order_by']
        results = [r for r in results if r['score'] > 1e-9]
        results = sorted(results, key=lambda r: tuple(r[k] for k in order_by), reverse=True)

        with transaction.atomic():
            fields = set()

            pks = set()
            last_score = None
            place = None
            for index, row in enumerate(tqdm.tqdm(results, desc=f'update statistics for stage {stage}'), start=1):
                curr_score = tuple(row[k] for k in order_by)
                if curr_score != last_score:
                    last_score = curr_score
                    place = index

                account = row.pop('member')
                solving = row.pop('score')
                stat, created = Statistics.objects.update_or_create(
                    account=account,
                    contest=stage,
                    defaults={
                        'place': str(place),
                        'place_as_int': place,
                        'solving': solving,
                        'addition': row,
                    },
                )
                pks.add(stat.pk)

                for k in row.keys():
                    fields.add(k)
            stage.statistics_set.exclude(pk__in=pks).delete()

            stage.info['fields'] = list(fields)

        if 'points' in order_by:
            stage.info['fixed_fields'] = [('points', 'Points')]
        stage.info['problems'] = list(problems_infos.values())
        stage.save()
