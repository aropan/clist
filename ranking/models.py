import ast
import collections
from urllib.parse import quote_plus

import tqdm
from django.db import models, transaction
from django.db.models.signals import pre_save, m2m_changed, post_save, post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.contrib.postgres.fields import JSONField
from django_countries.fields import CountryField


from pyclist.models import BaseModel
from true_coders.models import Coder, Party
from clist.models import Contest, Resource
from clist.templatetags.extras import slug, get_number_from_str


class Account(BaseModel):
    coders = models.ManyToManyField(Coder, blank=True)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    key = models.CharField(max_length=1024, null=False, blank=False)
    name = models.CharField(max_length=1024, null=True, blank=True)
    country = CountryField(null=True, blank=True, db_index=True)
    url = models.CharField(max_length=4096, null=True, blank=True)
    n_contests = models.IntegerField(default=0, db_index=True)
    last_activity = models.DateTimeField(default=None, null=True, blank=True, db_index=True)
    rating = models.IntegerField(default=None, null=True, blank=True, db_index=True)
    rating50 = models.SmallIntegerField(default=None, null=True, blank=True, db_index=True)
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
        indexes = [
            models.Index(fields=['resource', 'country']),
            models.Index(fields=['resource', 'last_activity', 'country']),
            models.Index(fields=['resource', 'n_contests', '-id']),
            models.Index(fields=['resource', 'last_activity', '-id']),
            models.Index(fields=['resource', 'rating', '-id']),
            models.Index(fields=['resource', 'rating50']),
        ]

        unique_together = ('resource', 'key')


@receiver(pre_save, sender=Account)
def set_account_rating(sender, instance, *args, **kwargs):
    instance.rating = instance.info.get('rating')
    instance.rating50 = instance.rating / 50 if instance.rating is not None else None


@receiver(post_save, sender=Account)
@receiver(post_delete, sender=Account)
def count_resource_accounts(signal, instance, **kwargs):
    if signal is post_delete:
        instance.resource.n_accounts -= 1
        instance.resource.save()
    elif signal is post_save and kwargs['created']:
        instance.resource.n_accounts += 1
        instance.resource.save()


@receiver(pre_save, sender=Account)
@receiver(m2m_changed, sender=Account.coders.through)
def update_account_url(signal, instance, **kwargs):

    def default_url():
        args = [quote_plus(instance.key), quote_plus(instance.resource.host)]
        return reverse('coder:account', args=args)

    if signal is pre_save:
        if instance.url:
            return
        instance.url = default_url()
    elif signal is m2m_changed:
        if not kwargs.get('action').startswith('post_'):
            return
        url = None
        for coder in instance.coders.iterator():
            if url is not None:
                url = None
                break
            url = reverse('coder:profile', args=[coder.username])
        instance.url = url
        instance.save()


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


@receiver(pre_save, sender=Statistics)
def statistics_pre_save(sender, instance, *args, **kwargs):
    instance.place_as_int = get_number_from_str(instance.place)


@receiver(post_save, sender=Statistics)
@receiver(post_delete, sender=Statistics)
def count_account_contests(signal, instance, **kwargs):
    if instance.addition.get('_no_update_n_contests'):
        return

    if signal is post_delete:
        instance.account.n_contests -= 1
        instance.account.save()
    elif signal is post_save and kwargs['created']:
        instance.account.n_contests += 1

        if not instance.account.last_activity or instance.account.last_activity < instance.contest.start_time:
            instance.account.last_activity = instance.contest.start_time

        instance.account.save()


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
        advances = self.score_params.get('advances', {})
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

        exclude_advances = {}
        if advances and advances.get('exclude_stages'):
            qs = Statistics.objects \
                .filter(contest__stage__in=advances['exclude_stages'], addition___advance__isnull=False) \
                .values('account__key', 'addition___advance', 'contest__title') \
                .order_by('contest__end_time')
            for r in qs:
                d = r['addition___advance']
                if 'contest' not in d:
                    d['contest'] = r['contest__title']
                exclude_advances[r['account__key']] = d

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
                        if 'type' in field:
                            continue
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

                    if 'status' in self.score_params:
                        field = self.score_params['status']
                        problem['status'] = field_values.get(field, row.get(field))
                    else:
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

        for field in fields:
            t = field.get('type')
            if t == 'points_for_common_problems':
                group = field['group']
                inp = field['field']
                out = field.get('out', inp)

                common_problems = dict()
                for account, row in results.items():
                    problems = set(row['problems'].keys())
                    key = row[group]
                    common_problems[key] = problems if key not in common_problems else (problems & common_problems[key])

                for account, row in results.items():
                    key = row[group]
                    problems = common_problems[key]
                    value = 0
                    for k in problems:
                        value += float(row['problems'].get(k, {}).get(inp, 0))
                    for k, v in row['problems'].items():
                        if k not in problems:
                            v['status_tag'] = 'strike'
                    row[out] = round(value, 2)

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
            score_advance = None
            place_advance = 0
            for index, row in enumerate(tqdm.tqdm(results, desc=f'update statistics for stage {stage}'), start=1):
                curr_score = tuple(row[k.lstrip('-')] for k in order_by)
                if curr_score != last_score:
                    last_score = curr_score
                    place = index

                if advances:
                    tmp = score_advance, place_advance
                    if curr_score != score_advance:
                        score_advance = curr_score
                        place_advance += 1

                    for advance in advances.get('options', []):
                        handle = row['member'].key
                        if handle in exclude_advances and advance['next'] == exclude_advances[handle]['next']:
                            advance = exclude_advances[handle]
                            if 'class' in advance and not advance['class'].startswith('text-'):
                                advance['class'] = f'text-{advance["class"]}'
                            row['_advance'] = advance
                            break

                        if 'places' in advance and place_advance in advance['places']:
                            row['_advance'] = advance
                            tmp = None
                            break

                    if tmp is not None:
                        score_advance, place_advance = tmp

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

        standings_info = self.score_params.get('info', {})
        standings_info['fixed_fields'] = [(f.lstrip('-'), f.lstrip('-')) for f in order_by]
        stage.info['standings'] = standings_info

        stage.info['problems'] = list(problems_infos.values())
        stage.save()
