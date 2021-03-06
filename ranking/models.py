import re
import ast
import collections
from copy import deepcopy
from pydoc import locate
from urllib.parse import urljoin

import tqdm
from django.db import models, transaction
from django.db.models import F
from django.db.models.signals import pre_save, m2m_changed, post_save, post_delete
from django.db.models.functions import Upper
from django.dispatch import receiver
from django.urls import reverse
from django.contrib.postgres.fields import JSONField
from django_countries.fields import CountryField
from django_print_sql import print_sql
from django_expression_index import ExpressionIndex


from pyclist.models import BaseModel
from pyclist.indexes import GistIndexTrgrmOps
from true_coders.models import Coder, Party
from clist.models import Contest, Resource
from clist.templatetags.extras import slug, get_number_from_str, get_problem_short, add_prefix_to_problem_short


class Account(BaseModel):
    coders = models.ManyToManyField(Coder, blank=True)
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE)
    key = models.CharField(max_length=1024, null=False, blank=False)
    name = models.CharField(max_length=1024, null=True, blank=True)
    country = CountryField(null=True, blank=True, db_index=True)
    url = models.CharField(max_length=4096, null=True, blank=True)
    n_contests = models.IntegerField(default=0, db_index=True)
    n_writers = models.IntegerField(default=0, db_index=True)
    last_activity = models.DateTimeField(default=None, null=True, blank=True, db_index=True)
    rating = models.IntegerField(default=None, null=True, blank=True, db_index=True)
    rating50 = models.SmallIntegerField(default=None, null=True, blank=True, db_index=True)
    info = JSONField(default=dict, blank=True)
    updated = models.DateTimeField(auto_now_add=True)
    duplicate = models.ForeignKey('Account', null=True, blank=True, on_delete=models.CASCADE)

    def __str__(self):
        return '%s on %s' % (str(self.key), str(self.resource_id))

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

    def avatar_url(self, resource=None):
        resource = resource or self.resource
        if resource.avatar_url:
            try:
                avatar_url_info = resource.info.get('avatar_url', {})
                fields = avatar_url_info.get('fields')
                if fields and any(not self.info.get(f) for f in fields):
                    return
                url = resource.avatar_url.format(key=self.key, info=self.info)
                if avatar_url_info.get('urljoin'):
                    url = urljoin(avatar_url_info.get('urljoin'), url)
                return url
            except KeyError:
                pass

    class Meta:
        indexes = [
            GistIndexTrgrmOps(fields=['key']),
            GistIndexTrgrmOps(fields=['name']),
            ExpressionIndex(expressions=[Upper('key')]),
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


def update_account_by_coders(instance, default_url=None):
    url = False
    custom_countries = None
    for idx, coder in enumerate(instance.coders.iterator()):
        if url:
            url = True
        else:
            url = reverse('coder:profile', args=[coder.username]) + f'?search=resource:{instance.resource.host}'

        if custom_countries is None:
            custom_countries = coder.settings.get('custom_countries', {})
        else:
            d = {}
            for k, v in coder.settings.get('custom_countries', {}).items():
                if custom_countries.get(k) == v:
                    d[k] = v
            custom_countries = d

            if idx >= 1 and not custom_countries:
                break

    if isinstance(url, bool):
        url = default_url

    if url:
        instance.url = url

    instance.info['custom_countries_'] = custom_countries or {}

    instance.save()


@receiver(pre_save, sender=Account)
@receiver(m2m_changed, sender=Account.coders.through)
def update_account_url(signal, instance, **kwargs):

    def default_url():
        args = [instance.key, instance.resource.host]
        return reverse('coder:account', args=args)

    if signal is pre_save:
        if instance.url:
            return
        instance.url = default_url()
    elif signal is m2m_changed:
        if not kwargs.get('action').startswith('post_'):
            return
        update_account_by_coders(instance, default_url=default_url())


@receiver(m2m_changed, sender=Account.writer_set.through)
def update_account_writer(signal, instance, action, reverse, pk_set, **kwargs):
    when, action = action.split('_', 1)
    if when != 'post':
        return
    if action == 'add':
        delta = 1
    elif action == 'remove':
        delta = -1
    else:
        return

    if reverse:
        instance.n_writers += delta
        instance.save()
    else:
        Account.objects.filter(pk__in=pk_set).update(n_writers=F('n_writers') + delta)


@receiver(m2m_changed, sender=Account.coders.through)
def update_n_coder_accounts(signal, instance, action, reverse, pk_set, **kwargs):
    when, action = action.split('_', 1)
    if when != 'post':
        return
    if action == 'add':
        delta = 1
    elif action == 'remove':
        delta = -1
    else:
        return

    if reverse:
        instance.n_accounts += delta
        instance.save()
    else:
        Coder.objects.filter(pk__in=pk_set).update(n_accounts=F('n_accounts') + delta)


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
            models.Index(fields=['place_as_int', '-created']),
            models.Index(fields=['contest', 'place_as_int', '-solving', 'id']),
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
        contests = contests.prefetch_related('writers')

        placing = self.score_params.get('place')
        n_best = self.score_params.get('n_best')
        fields = self.score_params.get('fields', [])
        detail_problems = self.score_params.get('detail_problems')
        order_by = self.score_params['order_by']
        advances = self.score_params.get('advances', {})
        results = collections.defaultdict(collections.OrderedDict)

        mapping_account_by_coder = {}

        problems_infos = collections.OrderedDict()
        divisions_order = []
        for idx, contest in enumerate(tqdm.tqdm(contests, desc=f'getting contests for stage {stage}'), start=1):
            info = {
                'code': str(contest.pk),
                'name': contest.title,
                'url': reverse(
                    'ranking:standings',
                    kwargs={'title_slug': slug(contest.title), 'contest_id': str(contest.pk)}
                ),
            }

            for division in contest.info.get('divisions_order', []):
                if division not in divisions_order:
                    divisions_order.append(division)

            problems = contest.info.get('problems', [])
            if not detail_problems:
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
                if self.score_params.get('regex_problem_name'):
                    match = re.search(self.score_params.get('regex_problem_name'), contest.title)
                    if match:
                        info['short'] = match.group(1)
                if self.score_params.get('abbreviation_problem_name'):
                    info['short'] = ''.join(re.findall(r'(\b[A-Z]|[0-9])', info.get('short', contest.title)))
                problems_infos[str(contest.pk)] = info
            else:
                for problem in problems:
                    problem = dict(problem)
                    add_prefix_to_problem_short(problem, f'{idx}.')
                    problem['group'] = info['name']
                    problem['url'] = info['url']
                    problems_infos[get_problem_short(problem)] = problem

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

        statistics = Statistics.objects \
            .select_related('account', 'account__duplicate') \
            .prefetch_related('account__coders')
        filter_statistics = self.score_params.get('filter_statistics')
        if filter_statistics:
            statistics = statistics.filter(**filter_statistics)

        def get_placing(placing, stat):
            return placing['division'][stat.addition['division']] if 'division' in placing else placing

        account_keys = dict()
        total = statistics.filter(contest__in=contests).count()
        with tqdm.tqdm(total=total, desc=f'getting statistics for stage {stage}') as pbar, print_sql(count_only=True):
            for idx, contest in enumerate(contests, start=1):
                skip_problem_stat = '_skip_for_problem_stat' in contest.info.get('fields', [])
                contest_unrated = contest.info.get('unrated')

                if not detail_problems:
                    problem_info_key = str(contest.pk)
                    problem_short = get_problem_short(problems_infos[problem_info_key])
                pbar.set_postfix(contest=contest)
                stats = statistics.filter(contest_id=contest.pk)

                if placing:
                    placing_scores = deepcopy(placing)
                    n_rows = 0
                    for s in stats:
                        n_rows += 1
                        placing_ = get_placing(placing_scores, s)
                        key = str(s.place_as_int)
                        if key in placing_:
                            placing_.setdefault('scores', {})
                            placing_['scores'][key] = placing_.pop(key)
                    scores = []
                    for place in reversed(range(1, n_rows + 1)):
                        placing_ = get_placing(placing_scores, s)
                        key = str(place)
                        if key in placing_:
                            scores.append(placing_.pop(key))
                        else:
                            if scores:
                                placing_['scores'][key] += sum(scores)
                                placing_['scores'][key] /= len(scores) + 1
                            scores = []

                for s in stats:
                    if not detail_problems and not skip_problem_stat:
                        problems_infos[problem_info_key].setdefault('n_total', 0)
                        problems_infos[problem_info_key]['n_total'] += 1

                    if s.solving < 1e-9:
                        score = 0
                    else:
                        if placing:
                            placing_ = get_placing(placing_scores, s)
                            score = placing_['scores'].get(str(s.place_as_int), placing_.get('default'))
                            if score is None:
                                continue
                        else:
                            score = s.solving

                    if not detail_problems and not skip_problem_stat:
                        problems_infos[problem_info_key].setdefault('n_teams', 0)
                        problems_infos[problem_info_key]['n_teams'] += 1
                        if score:
                            problems_infos[problem_info_key].setdefault('n_accepted', 0)
                            problems_infos[problem_info_key]['n_accepted'] += 1

                    account = s.account
                    if account.duplicate is not None:
                        account = account.duplicate

                    coders = account.coders.all()
                    has_mapping_account_by_coder = False
                    if len(coders) == 1:
                        coder = coders[0]
                        if coder not in mapping_account_by_coder:
                            mapping_account_by_coder[coder] = account
                        else:
                            account = mapping_account_by_coder[coder]
                            has_mapping_account_by_coder = True

                    row = results[account]
                    row['member'] = account
                    account_keys[account.key] = account

                    problems = row.setdefault('problems', {})
                    if detail_problems:
                        for key, problem in s.addition.get('problems', {}).items():
                            problems[f'{idx}.' + key] = problem
                    else:
                        problem = problems.setdefault(problem_short, {})
                        if contest_unrated:
                            problem = problem.setdefault('upsolving', {})
                        problem['result'] = score
                        url = s.addition.get('url')
                        if url:
                            problem['url'] = url
                    if contest_unrated:
                        score = 0

                    if n_best and not detail_problems:
                        row.setdefault('scores', []).append((score, problem))
                    else:
                        row['score'] = row.get('score', 0) + score

                    field_values = {}
                    for field in fields:
                        inp = field['field']
                        out = field.get('out', inp)
                        if field.get('skip_on_mapping_account_by_coder') and has_mapping_account_by_coder:
                            continue
                        if 'type' in field:
                            continue
                        if field.get('first') and out in row or (inp not in s.addition and not hasattr(s, inp)):
                            continue
                        val = s.addition[inp] if inp in s.addition else getattr(s, inp)
                        if not field.get('safe') and isinstance(val, str):
                            val = ast.literal_eval(val)
                        if 'cast' in field:
                            val = locate(field['cast'])(val)
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
                        val = field_values.get(field, row.get(field))
                        if val is None:
                            val = getattr(s, field)
                        if val:
                            problem['status'] = val
                    else:
                        for field in order_by:
                            field = field.lstrip('-')
                            if field in ['score', 'rating']:
                                continue
                            status = field_values.get(field, row.get(field))
                            if status is None:
                                continue
                            problem['status'] = status
                            break

                    pbar.update()

        for writer in contest.writers.all():
            account_keys[writer.key] = writer
        total = sum([len(contest.info.get('writers', [])) for contest in contests])
        with tqdm.tqdm(total=total, desc=f'getting writers for stage {stage}') as pbar, print_sql(count_only=True):
            writers = set()
            for contest in contests:
                contest_writers = contest.info.get('writers', [])
                if not contest_writers or detail_problems:
                    continue
                problem_info_key = str(contest.pk)
                problem_short = get_problem_short(problems_infos[problem_info_key])
                for writer in contest_writers:
                    if writer in account_keys:
                        account = account_keys[writer]
                    else:
                        try:
                            account = Account.objects.get(resource_id=contest.resource_id, key__iexact=writer)
                        except Account.DoesNotExist:
                            account = None

                    pbar.update()
                    if not account:
                        continue
                    writers.add(account)

                    row = results[account]
                    row['member'] = account
                    row.setdefault('score', 0)
                    if n_best:
                        row.setdefault('scores', [])
                    row.setdefault('writer', 0)

                    row['writer'] += 1

                    problems = row.setdefault('problems', {})
                    problem = problems.setdefault(problem_short, {})
                    problem['status'] = 'W'

        if self.score_params.get('writers_proportionally_score'):
            n_contests = len(contests)
            for account in writers:
                row = results[account]
                if n_contests == row['writer'] or 'score' not in row:
                    continue
                row['score'] = row['score'] / (n_contests - row['writer']) * n_contests

        for field in fields:
            t = field.get('type')
            if t == 'points_for_common_problems':
                group = field['group']
                inp = field['field']
                out = field.get('out', inp)

                common_problems = dict()
                for account, row in results.items():
                    problems = {k for k, p in row['problems'].items() if p.get('status') != 'W'}
                    key = row[group]
                    common_problems[key] = problems if key not in common_problems else (problems & common_problems[key])

                for account, row in results.items():
                    key = row[group]
                    problems = common_problems[key]
                    value = 0
                    for k in problems:
                        value += float(row['problems'].get(k, {}).get(inp, 0))
                    for k, v in row['problems'].items():
                        if k not in problems and v.get('status') != 'W':
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

        filtered_results = []
        for r in results:
            if r['score'] > 1e-9 or r.get('writer'):
                filtered_results.append(r)
                continue
            if detail_problems:
                continue

            problems = r.setdefault('problems', {})

            for idx, contest in enumerate(contests, start=1):
                skip_problem_stat = '_skip_for_problem_stat' in contest.info.get('fields', [])
                if skip_problem_stat:
                    continue

                problem_info_key = str(contest.pk)
                problem_short = get_problem_short(problems_infos[problem_info_key])

                if problem_short in problems:
                    problems_infos[problem_info_key].setdefault('n_teams', 0)
                    problems_infos[problem_info_key]['n_teams'] -= 1
        results = filtered_results

        results = sorted(
            results,
            key=lambda r: tuple(r.get(k.lstrip('-'), 0) * (-1 if k.startswith('-') else 1) for k in order_by),
            reverse=True,
        )

        with transaction.atomic():
            fields_set = set()
            fields = list()

            pks = set()
            placing_infos = {}
            score_advance = None
            place_advance = 0
            for row in tqdm.tqdm(results, desc=f'update statistics for stage {stage}'):
                division = row.get('division', 'none')
                placing_info = placing_infos.setdefault(division, {})
                placing_info['index'] = placing_info.get('index', 0) + 1

                curr_score = tuple(row.get(k.lstrip('-'), 0) for k in order_by)
                if curr_score != placing_info.get('last_score'):
                    placing_info['last_score'] = curr_score
                    placing_info['place'] = placing_info['index']

                if advances and ('divisions' not in advances or division in advances['divisions']):
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
                            for field in advance.get('inplace_fields', []):
                                row[field] = advance[field]
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
                        'place': str(placing_info['place']),
                        'place_as_int': placing_info['place'],
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
            stage.n_statistics = len(results)

            stage.info['fields'] = list(fields)

        standings_info = self.score_params.get('info', {})
        standings_info['fixed_fields'] = [(f.lstrip('-'), f.lstrip('-')) for f in order_by]
        stage.info['standings'] = standings_info

        if divisions_order and self.score_params.get('divisions_ordering'):
            stage.info['divisions_order'] = divisions_order

        stage.info['problems'] = list(problems_infos.values())
        stage.save()
