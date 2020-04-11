import re
import ast
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

    class Meta:
        unique_together = ('contest', 'party')


class AutoRating(BaseModel):
    party = models.ForeignKey(Party, on_delete=models.CASCADE)
    info = JSONField(default=dict, blank=True)
    deadline = models.DateTimeField()

    def __str__(self):
        return 'auto rating [%d] with party [%d]' % (self.pk, self.party_id)


class Statistics(BaseModel):
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE)
    place = models.CharField(max_length=17, default=None, null=True, blank=True)
    place_as_int = models.IntegerField(default=None, null=True, blank=True)
    solving = models.FloatField(default=0, blank=True)
    upsolving = models.FloatField(default=0, blank=True)
    addition = JSONField(default=dict, blank=True)
    url = models.TextField(null=True, blank=True)

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

        placing = self.score_params.get('place')
        n_best = self.score_params.get('n_best')
        fields = self.score_params.get('fields', [])
        order_by = self.score_params['order_by']
        results = collections.defaultdict(collections.OrderedDict)

        problems_infos = collections.OrderedDict()
        for contest in tqdm.tqdm(contests, desc=f'getting contests for stage {stage}'):
            info = {
                'code': str(contest.pk),
                'name': contest.title,
                'url': reverse(
                    'ranking:standings',
                    kwargs={'title_slug': slug(contest.title), 'contest_id': str(contest.pk)}
                ),
                'n_accepted': 0,
                'n_teams': 0,
            }

            problems = contest.info.get('problems', [])
            full_score = None
            if placing:
                if 'division' in placing:
                    full_score = max([max(p.values()) for p in placing['division'].values()])
                else:
                    full_score = max(placing.values())
            elif 'division' in problems:
                full_scores = []
                for ps in problems['division'].values():
                    full = 0
                    for problem in ps:
                        full += problem.get('full_score', 1)
                    full_scores.append(full)
                info['full_score'] = max(full_scores)
            else:
                full_score = 0
                for problem in problems:
                    full_score += problem.get('full_score', 1)
            if full_score is not None:
                info['full_score'] = full_score

            problems_infos[contest.pk] = info

        statistics = Statistics.objects.select_related('account')
        filter_statistics = self.score_params.get('filter_statistics')
        if filter_statistics:
            statistics = statistics.filter(**filter_statistics)

        total = statistics.filter(contest__in=contests).count()
        with tqdm.tqdm(total=total, desc=f'getting statistics for stage {stage}') as pbar:
            for contest in contests:
                pbar.set_postfix(contest=contest)
                stats = statistics.filter(contest_id=contest.pk)

                for s in stats.iterator():
                    row = results[s.account]
                    row['member'] = s.account

                    problems_infos[contest.pk]['n_teams'] += 1

                    if s.solving < 1e-9:
                        score = 0
                    else:
                        problems_infos[contest.pk]['n_accepted'] += 1
                        if placing:
                            placing_ = placing['division'][s.addition['division']] if 'division' in placing else placing
                            score = placing_.get(str(s.place_as_int), placing_['default'])
                        else:
                            score = s.solving

                    problems = row.setdefault('problems', {})
                    problem = problems.setdefault(str(contest.pk), {})
                    problem['result'] = score
                    url = s.addition.get('url')
                    if url:
                        problem['url'] = url

                    if n_best:
                        row.setdefault('scores', []).append((score, problem))
                    else:
                        row['score'] = row.get('score', 0) + score

                    field_values = {}
                    for field in fields:
                        inp = field['field']
                        out = field.get('out', inp)
                        if field.get('first') and out in row or inp not in s.addition:
                            continue
                        val = ast.literal_eval(str(s.addition[inp]))
                        field_values[out] = val
                        if field.get('accumulate'):
                            val = round(val + ast.literal_eval(str(row.get(out, 0))), 2)
                        row[out] = val

                    if 'solved' in s.addition:
                        solved = row.setdefault('solved', {})
                        for k, v in s.addition['solved'].items():
                            solved[k] = solved.get(k, 0) + v

                    for field in order_by:
                        field = field.lstrip('-')
                        if field == 'score':
                            continue
                        status = field_values.get(field, row.get(field))
                        if status is None:
                            continue
                        problem['status'] = status
                        break

                    pbar.update()

        results = list(results.values())
        if n_best:
            for row in results:
                scores = row.pop('scores')
                for index, (score, problem) in enumerate(sorted(scores, key=lambda s: s[0], reverse=True)):
                    if index < n_best:
                        row['score'] = row.get('score', 0) + score
                    else:
                        problem['status'] = problem.pop('result')

        results = [r for r in results if r['score'] > 1e-9]
        results = sorted(
            results,
            key=lambda r: tuple(r[k.lstrip('-')] * (-1 if k.startswith('-') else 1) for k in order_by),
            reverse=True,
        )

        with transaction.atomic():
            fields_set = set()
            fields = list()

            pks = set()
            last_score = None
            place = None
            for index, row in enumerate(tqdm.tqdm(results, desc=f'update statistics for stage {stage}'), start=1):
                curr_score = tuple(row[k.lstrip('-')] for k in order_by)
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
                    if k not in fields_set:
                        fields_set.add(k)
                        fields.append(k)
            stage.statistics_set.exclude(pk__in=pks).delete()

            stage.info['fields'] = list(fields)

        stage.info['standings'] = {'fixed_fields': [(f.lstrip('-'), f.lstrip('-').title()) for f in order_by]}
        stage.info['problems'] = list(problems_infos.values())
        stage.save()
