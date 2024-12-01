#!/usr/bin/env python3

import ast
import collections
import functools
import json
import operator
import re
from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
from pydoc import locate

import tqdm
from django.conf import settings
from django.core.management import call_command
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django_print_sql import print_sql
from django_super_deduper.merge import MergedModelInstance
from sql_util.utils import Exists

from clist.templatetags.extras import add_prefix_to_problem_short, get_item, get_problem_short, slug
from ranking.management.modules.common import LOG
from ranking.models import Account, AccountRenaming, Statistics
from utils.logger import suppress_db_logging_context
from utils.mathutils import max_with_none


@transaction.atomic
def rename_account(old_account, new_account):
    AccountRenaming.objects.update_or_create(
        resource=old_account.resource,
        old_key=old_account.key,
        defaults={'new_key': new_account.key},
    )
    AccountRenaming.objects.filter(
        resource=old_account.resource,
        old_key=new_account.key,
    ).delete()

    new_contests = new_account.statistics_set.filter(skip_in_stats=False).values('contest')
    old_account.statistics_set.filter(contest__in=new_contests).delete()
    old_contests = old_account.statistics_set.values('contest')
    new_account.statistics_set.filter(contest__in=old_contests).delete()

    n_contests = new_account.n_contests + old_account.n_contests
    n_writers = new_account.n_writers + old_account.n_writers
    last_activity = max_with_none(old_account.last_activity, new_account.last_activity)
    last_submission = max_with_none(old_account.last_submission, new_account.last_submission)
    new_account = MergedModelInstance.create(new_account, [old_account])
    old_account.delete()
    new_account.n_contests = n_contests
    new_account.n_writers = n_writers
    new_account.last_activity = last_activity
    new_account.last_submission = last_submission
    new_account.save()
    return new_account


def clear_problems_fields(problems, submitted_keys=None):
    if not problems:
        return
    to_remove = []
    for k, v in problems.items():
        if not isinstance(v, dict):
            continue
        v.pop('first_ac', None)
        v.pop('first_ac_of_all', None)

        if submitted_keys is not None and k not in submitted_keys:
            upsolving = v.pop('upsolving', None)
            v.clear()
            if upsolving:
                v['upsolving'] = upsolving
            if not v:
                to_remove.append(k)
    for k in to_remove:
        problems.pop(k)


def to_canonize_str(data):
    return json.dumps(data, sort_keys=True)


def renaming_check(account, contest_keys, fields, contest_addition_update):
    if len(contest_keys) < 3:
        return
    key_counter = defaultdict(int)
    total_counter = 0
    max_counter_key = None
    queryset_filter = Q()
    for contest_key in contest_keys:
        addition_update = contest_addition_update[contest_key]
        if '_rank' not in addition_update:
            continue
        rank_field = addition_update.get('_rank_field', 'place')
        total_counter += 1
        conditions = (Q(**{f'contest__{field}': contest_key}) for field in fields)
        condition = functools.reduce(operator.__or__, conditions)
        condition &= Q(contest__resource=account.resource)
        condition &= Q(**{rank_field: addition_update['_rank']})
        queryset_filter |= condition
    if not queryset_filter:
        return
    for contest_id, old_account_key in tqdm.tqdm(
        Statistics.objects.filter(queryset_filter).values_list('contest_id', 'account__key').iterator(),
        total=total_counter,
        desc='renaming check',
    ):
        if old_account_key == account.key:
            continue
        key_counter[old_account_key] += 1
        if max_counter_key is None or key_counter[max_counter_key] < key_counter[old_account_key]:
            max_counter_key = old_account_key
    if max_counter_key is None:
        return

    account.try_renaming_check_time = timezone.now()
    account.save(update_fields=['try_renaming_check_time'])

    max_counter_val = key_counter.pop(max_counter_key)
    other_max_counter_val = max(key_counter.values(), default=0)
    threshold_val = max(other_max_counter_val * 2, 3)
    if max_counter_val < threshold_val:
        LOG.warning('Failed renaming %s, max_key = %s, max_val = %d, threshold = %d, n_counters = %d',
                    account, max_counter_key, max_counter_val, threshold_val, len(key_counter))
        return
    old_account = account.resource.account_set.get(key=max_counter_key)
    LOG.info('Renaming %s to %s', old_account, account)
    rename_account(old_account, account)
    return True


def fill_missed_ranks(account, contest_keys, fields, contest_addition_update):
    account.save()
    ok = False
    updated = 0
    missed = 0
    total = 0
    filled_groups = set()
    missed_grouped_contest_keys = list()
    seen_groups = set()
    for contest_key in tqdm.tqdm(contest_keys, desc='fill missed ranks', total=len(contest_keys)):
        addition_update = contest_addition_update[contest_key]
        if '_rank' not in addition_update:
            continue

        group = addition_update.get('_group')
        if not group or group not in seen_groups:
            total += 1
        if group:
            seen_groups.add(group)

        rank = addition_update['_rank']
        rank_field = addition_update.get('_rank_field', 'place_as_int')
        conditions = (Q(**{f'{field}': contest_key}) for field in fields)
        condition = functools.reduce(operator.__or__, conditions)
        base_contests = account.resource.contest_set.filter(condition)
        qs = base_contests.annotate(has_rank=Exists('statistics', filter=Q(**{rank_field: rank})))
        contests = list(qs.filter(has_rank=False))
        if not contests:
            qs = base_contests.annotate(has_skip=Exists('statistics', filter=Q(
                place_as_int=rank, skip_in_stats=True, account=account
            )))
            contests = list(qs.filter(has_skip=True))
        if not contests:
            contests = list(base_contests)
            if len(contests) == 0:
                if not group:
                    LOG.info('Not found contest with key %s, fields = %s', contest_key, fields)
                else:
                    missed_grouped_contest_keys.append(contest_key)
                continue
            if len(contests) == 1 and not addition_update.get('_with_create'):
                missed += 1
                LOG.info('Missed #%d rank %s for %s in %s', missed,  rank, account, contests[0])
                continue
        if len(contests) > 1:
            LOG.warning('Multiple contests with same key %s = %s', contest_key, contests)
            continue
        defaults = {'skip_in_stats': False}
        if '_rank_field' not in addition_update:
            defaults['place'] = rank
            defaults['place_as_int'] = rank
        contest = contests[0]
        updated += 1
        statistic, created = Statistics.objects.update_or_create(account=account, contest=contest, defaults=defaults)
        statistic.addition.pop('_no_update_n_contests', None)
        statistic.addition['_skip_on_update'] = True
        if account.name:
            statistic.addition['name'] = account.name
        statistic.save(update_fields=['addition'])
        if created:
            ok = True
        if group:
            filled_groups.add(group)
    for contest_key in missed_grouped_contest_keys:
        group = contest_addition_update[contest_key]['_group']
        if group not in filled_groups:
            LOG.info('Not found contest with key %s, fields = %s, group = %s', contest_key, fields, group)
    if total:
        account.try_fill_missed_ranks_time = timezone.now()
        account.save(update_fields=['try_fill_missed_ranks_time'])
    if updated:
        LOG.info('Filled %d missed ranks (%d missed) of %d for %s', updated, missed, total, account)
    account.refresh_from_db()
    return ok


@suppress_db_logging_context()
def account_update_contest_additions(
    account,
    contest_addition_update,
    timedelta_limit=None,
    by=None,
    clear_rating_change=None,
    try_renaming_check=None,
    try_fill_missed_ranks=None,
):
    contest_keys = set(contest_addition_update.keys())

    fields = 'key' if by is None else by
    if isinstance(fields, str):
        fields = [fields]

    base_qs = Statistics.objects.filter(account=account)
    if timedelta_limit is not None and not clear_rating_change:
        base_qs.filter(modified__lte=timezone.now() - timedelta_limit)

    grouped_contest_keys = defaultdict(list)
    for contest_key, update in contest_addition_update.items():
        group = update.get('_group')
        if group:
            grouped_contest_keys[group].append(contest_key)

    iteration = 0
    renaming_contest_keys = set(contest_keys)
    while contest_keys:
        iteration += 1
        if clear_rating_change:
            qs_clear = base_qs.filter(Q(addition__rating_change__isnull=False) |
                                      Q(addition__new_rating__isnull=False) |
                                      Q(addition__rating__isnull=False))
            for s in qs_clear:
                s.addition.pop('rating', None)
                s.addition.pop('rating_change', None)
                s.addition.pop('new_rating', None)
                s.addition.pop('old_rating', None)
                s.save(update_fields=['addition'])
            clear_rating_change = False

        conditions = (Q(**{f'contest__{field}__in': contest_keys}) for field in fields)
        condition = functools.reduce(operator.__or__, conditions)
        stat_qs = base_qs.filter(condition).select_related('contest')

        total = 0
        for stat in stat_qs:
            contest = stat.contest
            for field in fields:
                key = getattr(contest, field)
                contest_keys.discard(key)
                if not stat.skip_in_stats:
                    renaming_contest_keys.discard(key)

            total += 1
            addition = dict(stat.addition)
            for field in fields:
                key = getattr(contest, field)
                if key in contest_addition_update:
                    ordered_dict = contest_addition_update[key]
                    break

            group = ordered_dict.pop('_group', None)
            if group:
                for contest_key in grouped_contest_keys.pop(group, []):
                    contest_keys.discard(contest_key)
                    renaming_contest_keys.discard(contest_key)

            if stat.place is None:
                rank = ordered_dict.pop('_rank', None)
                if rank is not None and '_rank_field' not in ordered_dict:
                    LOG.info('Rank without rank_field for %s in %s = %s', account, contest, rank)
                    stat.place = rank
                    stat.place_as_int = rank
                    stat.save(update_fields=['place', 'place_as_int'])

            for k in [k for k in ordered_dict if k.startswith('_')]:
                ordered_dict.pop(k)

            addition.update(dict(ordered_dict))
            for k, v in ordered_dict.items():
                if v is None:
                    addition.pop(k)
            if to_canonize_str(stat.addition) == to_canonize_str(addition):
                continue
            stat.addition = addition
            stat.save(update_fields=['addition'])

            account.update_last_rating_activity(statistic=stat, contest=contest, resource=account.resource)

            to_save = False
            contest_fields = contest.info.setdefault('fields', [])
            external_fields = contest.info.setdefault('_external_fields', [])
            updated_external_fields = False
            for k in ordered_dict.keys():
                if k not in contest_fields:
                    contest_fields.append(k)
                    to_save = True
                    if k not in external_fields:
                        external_fields.append(k)
                        updated_external_fields = True
            if to_save:
                if updated_external_fields and contest.end_time + timedelta(days=31) > timezone.now():
                    contest.wait_for_successful_update_timing = timezone.now() + timedelta(days=1)
                contest.save()
        if iteration > 1 and not total:
            break

        if try_renaming_check and account.try_renaming_check_time is None:
            try_renaming_check = False
            if renaming_check(account, renaming_contest_keys, fields, contest_addition_update):
                try_fill_missed_ranks = False
                continue
        if try_fill_missed_ranks:
            try_fill_missed_ranks = False
            if fill_missed_ranks(account, renaming_contest_keys, fields, contest_addition_update):
                continue
        if contest_keys:
            out_contests = list(grouped_contest_keys.items()) or list(contest_keys)
            LOG.warning('Not found %d contests for %s = %s%s',
                        len(out_contests), account, out_contests[:5], '...' if len(out_contests) > 5 else '')
        break


def create_upsolving_statistic(contest, account):
    defaults = {
        'skip_in_stats': True,
        'addition': {'_no_update_n_contests': True},
    }
    if account.name:
        defaults['addition']['name'] = account.name
    stat, created = Statistics.objects.get_or_create(contest=contest, account=account, defaults=defaults)
    if stat.skip_in_stats or stat.is_rated:
        return stat, created

    problems = stat.addition.get('problems', {})
    all_upsolving = True
    for solution in problems.values():
        if len(solution) != 1 or 'upsolving' not in solution:
            all_upsolving = False
            break
    if all_upsolving:
        stat.skip_in_stats = True
        stat.addition['_no_update_n_contests'] = True
        stat.save(update_fields=['skip_in_stats', 'addition'])
    return stat, created


def update_stage(self):
    eps = 1e-9
    stage = self.contest
    timezone_now = timezone.now()

    filter_params = dict(self.filter_params)
    spec_filter_params = dict()
    for field in ('info__fields_types__new_rating__isnull',):
        if field in filter_params:
            spec_filter_params[field] = filter_params.pop(field)
    is_over = self.contest.end_time < timezone_now

    contests = self.contest.resource.contest_set.filter(
        start_time__gte=self.contest.start_time,
        end_time__lte=self.contest.end_time,
        **filter_params,
    ).exclude(pk=self.contest.pk)

    if spec_filter_params:
        contests = contests.filter(Q(**spec_filter_params) | Q(end_time__gt=timezone_now))

    contests = contests.order_by('start_time')
    contests = contests.prefetch_related('writers')
    self.contests.set(contests)

    parsed_statistic = self.score_params.get('parse_statistic')
    if parsed_statistic:
        call_command('parse_statistic',
                     contest_id=stage.pk,
                     without_set_coder_problems=True,
                     ignore_stage=True)
        stage.refresh_from_db()

    placing = self.score_params.get('place')
    n_best = self.score_params.get('n_best')
    fields = self.score_params.get('fields', [])
    scoring = self.score_params.get('scoring', {})
    detail_problems = self.score_params.get('detail_problems')
    order_by = self.score_params['order_by']
    advances = self.score_params.get('advances', {})
    results = collections.defaultdict(collections.OrderedDict)

    processed_fields = []
    for field in fields:
        if (many_fields := field.pop('fields', None)):
            for f in many_fields:
                field['field'] = f
                processed_fields.append(deepcopy(field))
        else:
            processed_fields.append(field)
    fields = processed_fields

    mapping_account_by_coder = {}
    fixed_fields = []
    hidden_fields = []

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

        if contest.start_time > timezone_now:
            info['subtext'] = {'text': 'upcoming', 'title': str(contest.start_time)}

        for division in contest.info.get('divisions_order', []):
            if division not in divisions_order:
                divisions_order.append(division)

        if self.score_params.get('regex_problem_name'):
            match = re.search(self.score_params.get('regex_problem_name'), contest.title)
            if match:
                info['short'] = match.group(1)
        if self.score_params.get('abbreviation_problem_name'):
            info['short'] = ''.join(re.findall(r'(\b[A-Z]|[0-9])', info.get('short', contest.title)))

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
            elif self.score_params.get('default_problem_full_score'):
                full_score = self.score_params['default_problem_full_score']
            else:
                full_score = 0
                for problem in problems:
                    full_score += problem.get('full_score', 1)
            if full_score is not None:
                info['full_score'] = full_score
            problems_infos[str(contest.pk)] = info
        else:
            for problem in problems:
                problem = dict(problem)
                add_prefix_to_problem_short(problem, f'{idx}.')
                problem['group'] = info.get('short', info['name'])
                problem['url'] = info['url']
                problems_infos[get_problem_short(problem)] = problem

    exclude_advances = {}
    if advances and advances.get('exclude_stages'):
        qs = Statistics.objects \
            .filter(contest__stage__in=advances['exclude_stages'], addition___advance__isnull=False) \
            .values('account__key', 'addition___advance', 'contest__title') \
            .order_by('contest__end_time', 'contest__id')
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
    exclude_statistics = self.score_params.get('exclude_statistics')
    if exclude_statistics:
        statistics = statistics.exclude(**exclude_statistics)
    re_ranking = self.score_params.get('re_ranking')

    def get_placing(placing, stat):
        return placing['division'][stat.addition['division']] if 'division' in placing else placing

    account_keys = dict()
    problem_values = defaultdict(set)
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

            max_solving = 0
            n_effective = 0
            for stat in stats:
                max_solving = max(max_solving, stat.solving)
                n_effective += stat.solving > eps

            if re_ranking:
                order = contest.get_statistics_order()
                stats = stats.order_by(*order)
                stat_rank = 0
                stat_last = None
                stat_attrs = [attr.strip('-') for attr in order]

            for stat_idx, stat in enumerate(stats, start=1):
                if not detail_problems and not skip_problem_stat:
                    problems_infos[problem_info_key].setdefault('n_total', 0)
                    problems_infos[problem_info_key]['n_total'] += 1

                if re_ranking:
                    stat_value = tuple(get_item(stat, attr) for attr in stat_attrs)
                    if stat_value != stat_last:
                        stat_rank = stat_idx
                        stat_last = stat_value
                    rank = stat_rank
                else:
                    rank = stat.place_as_int

                score = None
                if stat.solving < eps:
                    score = 0
                    if placing:
                        placing_ = get_placing(placing_scores, stat)
                        score = placing_.get('zero', 0)
                else:
                    if placing:
                        placing_ = get_placing(placing_scores, stat)
                        score = placing_['scores'].get(str(rank), placing_.get('default'))
                        if score is None:
                            continue
                if scoring:
                    if score is None:
                        score = 0
                    if scoring['name'] == 'general':
                        if rank is None:
                            continue
                        solving_factor = stat.solving / max_solving
                        rank_factor = (n_effective - rank + 1) / n_effective
                        score += scoring['factor'] * solving_factor * rank_factor
                    elif scoring['name'] == 'field':
                        score += stat.addition.get(scoring['field'], 0)
                    else:
                        raise NotImplementedError(f'scoring {scoring["name"]} is not implemented')
                if score is None:
                    score = stat.solving

                if not detail_problems and not skip_problem_stat:
                    problems_infos[problem_info_key].setdefault('n_teams', 0)
                    problems_infos[problem_info_key]['n_teams'] += 1
                    if score:
                        problems_infos[problem_info_key].setdefault('n_accepted', 0)
                        problems_infos[problem_info_key]['n_accepted'] += 1

                account = stat.account
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
                    for key, problem in stat.addition.get('problems', {}).items():
                        p = problems.setdefault(f'{idx}.' + key, {})
                        if contest_unrated:
                            p = p.setdefault('upsolving', {})
                        p.update(problem)
                else:
                    problem = problems.setdefault(problem_short, {})
                    if contest_unrated:
                        problem = problem.setdefault('upsolving', {})
                    problem['result'] = score
                    url = stat.addition.get('url')
                    if not url:
                        url = reverse('ranking:standings_by_id', kwargs={'contest_id': str(contest.pk)})
                        url += f'?find_me={stat.pk}'
                    problem['url'] = url
                if contest_unrated:
                    score = 0

                if n_best and not detail_problems:
                    row.setdefault('scores', []).append((score, problem))
                else:
                    row['score'] = row.get('score', 0) + score

                field_values = {}
                for field in fields:
                    if field.get('skip_on_mapping_account_by_coder') and has_mapping_account_by_coder:
                        continue
                    if 'type' in field:
                        continue
                    inp = field['field']
                    out = field.get('out', inp)
                    if field.get('first') and out in row or (inp not in stat.addition and not hasattr(stat, inp)):
                        continue
                    val = stat.addition[inp] if inp in stat.addition else getattr(stat, inp)
                    if not field.get('safe') and isinstance(val, str):
                        val = ast.literal_eval(val)
                    if 'cast' in field:
                        val = locate(field['cast'])(val)
                    field_values[out] = val
                    if field.get('skip'):
                        continue
                    if field.get('accumulate'):
                        val = round(val + ast.literal_eval(str(row.get(out, 0))), 2)
                    if field.get('aggregate') == 'avg':
                        out_n = f'_{out}_n'
                        out_s = f'_{out}_s'
                        row[out_n] = row.get(out_n, 0) + 1
                        row[out_s] = row.get(out_s, 0) + val
                        val = round(row[out_s] / row[out_n], 2)
                    if field.get('aggregate') == 'max' and out in row:
                        val = max(val, row[out])
                    row[out] = val

                for _, field, contest_field in settings.PROBLEM_STATISTIC_FIELDS:
                    values = stat.addition.get(field)
                    if not values:
                        continue
                    problem_values[contest_field] |= set(values)
                    row[field] = list(sorted(set(row.get(field, []) + values)))

                if 'solved' in stat.addition and isinstance(stat.addition['solved'], dict):
                    solved = row.setdefault('solved', {})
                    for k, v in stat.addition['solved'].items():
                        solved[k] = solved.get(k, 0) + v

                if 'status' in self.score_params:
                    field = self.score_params['status']
                    val = field_values.get(field, row.get(field))
                    if val is None:
                        val = getattr(stat, field)
                    if val is not None:
                        problem['status'] = val
                else:
                    for field in order_by:
                        field = field.lstrip('-')
                        if field in ['score', 'rating', 'penalty']:
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
        n_contests = sum(contest.start_time < timezone_now for contest in contests)
        for account in writers:
            row = results[account]
            if n_contests == row['writer'] or 'score' not in row:
                continue
            row['score'] = row['score'] / (n_contests - row['writer']) * n_contests
    if self.score_params.get('exponential_score_decay'):
        for r in results.values():
            scores = [problem.get('result', 0) for problem in r.get('problems', {}).values()]
            scores.sort(reverse=True)
            k = self.score_params['exponential_score_decay']
            score = k * sum((1 - k) ** i * score for i, score in enumerate(scores))
            r['score'] = score

    for field in fields:
        t = field.get('type')
        if t is None:
            continue
        if t == 'points_for_common_problems':
            group = field['group']
            inp = field['field']
            out = field.get('out', inp)

            excluding = bool(exclude_advances and field.get('exclude_advances'))

            groups = collections.defaultdict(list)
            for row in results.values():
                key = row[group]
                groups[key].append(row)

            advancement_position = 1
            for key, rows in sorted(groups.items(), key=lambda kv: kv[0], reverse=True):
                common_problems = None
                for row in rows:
                    handle = row['member'].key
                    if excluding and handle in exclude_advances:
                        exclude_advance = exclude_advances[handle]
                        for advance in advances.get('options', []):
                            if advance['next'] == exclude_advance['next']:
                                exclude_advance['skip'] = True
                                break
                            if advancement_position in advance['places']:
                                break
                        if exclude_advance.get('skip'):
                            continue

                    problems = {k for k, p in row['problems'].items() if p.get('status') != 'W'}
                    common_problems = problems if common_problems is None else (problems & common_problems)
                if common_problems is None:
                    for row in rows:
                        problems = {k for k, p in row['problems'].items() if p.get('status') != 'W'}
                        common_problems = problems if common_problems is None else (problems & common_problems)

                for row in rows:
                    handle = row['member'].key
                    if excluding and not exclude_advances.get(handle, {}).get('skip', False):
                        advancement_position += 1
                    value = 0
                    for k in common_problems:
                        value += float(row['problems'].get(k, {}).get(inp, 0))
                    for k, v in row['problems'].items():
                        if k not in common_problems and v.get('status') != 'W':
                            v['status_tag'] = 'strike'
                    row[out] = round(value, 2)
        elif t == 'region_by_country':
            out = field['out']

            mapping_regions = dict()
            for regional_event in field['data']:
                for region in regional_event['regions']:
                    mapping_regions[region['code']] = {'regional_event': regional_event, 'region': region}

            for row in results.values():
                country = row['member'].country
                if not country:
                    continue
                code = country.code
                if code not in mapping_regions:
                    continue
                row[out] = mapping_regions[code]['regional_event']['name']
        elif t == 'n_medal_problems':
            for row in results.values():
                for problem in row['problems'].values():
                    medal = problem.get('medal')
                    if medal:
                        k = f'n_{medal}_problems'
                        row.setdefault(k, 0)
                        row[k] += 1
                        if k not in hidden_fields:
                            hidden_fields.append(k)
            for field in settings.STANDINGS_FIELDS_:
                if field in hidden_fields:
                    fixed_fields.append(field)
                    hidden_fields.remove(field)
        else:
            raise ValueError(f'Unknown field type = {t}')

    hidden_fields += [field.get('out', field['field']) for field in fields if field.get('hidden')]

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
    filter_zero_points = self.score_params.get('filter_zero_points', True)
    for r in results:
        if r['score'] > eps or not filter_zero_points or r.get('writer'):
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

    additions = deepcopy(stage.info.get('additions', {}))
    field_to_problem = self.score_params.get('field_to_problem')
    with transaction.atomic():
        fields_set = set()
        fields = list()

        pks = set()
        placing_infos = {}
        score_advance = None
        place_advance = 0
        place_index = 0
        for row in tqdm.tqdm(results, desc=f'update statistics for stage {stage}'):
            for field in [row.get('member'), row.get('name')]:
                row.update(additions.pop(field, {}))

            division = row.get('division', 'none')
            placing_info = placing_infos.setdefault(division, {})
            placing_info['index'] = placing_info.get('index', 0) + 1

            curr_score = tuple(row.get(k.lstrip('-'), 0) for k in order_by)
            if curr_score != placing_info.get('last_score'):
                placing_info['last_score'] = curr_score
                placing_info['place'] = placing_info['index']

            if advances and ('divisions' not in advances or division in advances['divisions']):
                tmp = score_advance, place_advance, place_index

                place_index += 1
                if curr_score != score_advance:
                    score_advance = curr_score
                    place_advance = place_index

                for advance in advances.get('options', []):
                    handle = row['member'].key
                    if handle in exclude_advances and advance['next'] == exclude_advances[handle]['next']:
                        advance = exclude_advances[handle]
                        if 'class' in advance and not advance['class'].startswith('text-'):
                            advance['class'] = f'text-{advance["class"]}'
                        row['_advance'] = advance
                        break

                    if 'places' in advance and place_advance in advance['places']:
                        if not advances.get('inplace_fields_only'):
                            row['_advance'] = advance
                        if is_over:
                            for field in advance.get('inplace_fields', []):
                                row[field] = advance[field]
                        tmp = None
                        break

                if tmp is not None:
                    score_advance, place_advance, place_index = tmp
            account = row.pop('member')
            solving = row.pop('score')

            advanced = False
            if row.get('_advance'):
                adv = row['_advance']
                advanced = not adv.get('skip') and not adv.get('class', '').startswith('text-')

            defaults = {
                'place': str(placing_info['place']),
                'place_as_int': placing_info['place'],
                'solving': solving,
                'addition': row,
                'skip_in_stats': True,
                'advanced': advanced,
            }
            if parsed_statistic:
                defaults['place'] = None
                defaults['place_as_int'] = None
                defaults['solving'] = 0
                stat = Statistics.objects.filter(account=account, contest=stage).first()
                if not stat:
                    continue
                for k, v in defaults['addition'].items():
                    if k not in stat.addition or (v and not stat.addition.get(k)):
                        stat.addition[k] = v
                stat.skip_in_stats = defaults['skip_in_stats']
                stat.advanced = defaults['advanced']
                stat.save(update_fields=['addition', 'skip_in_stats', 'advanced'])
            else:
                stat, created = Statistics.objects.update_or_create(
                    account=account,
                    contest=stage,
                    defaults=defaults,
                )
            pks.add(stat.pk)

            for k in stat.addition.keys():
                if field_to_problem and re.search(field_to_problem['regex'], k):
                    continue
                if k not in fields_set:
                    fields_set.add(k)
                    fields.append(k)
        stage.info['problems'] = list(problems_infos.values())

        for contest_field, values in problem_values.items():
            stage.info[contest_field] = list(sorted(values))
        for _, field, contest_field in settings.PROBLEM_STATISTIC_FIELDS:
            if field not in fields_set and stage.info.get(contest_field):
                fields_set.add(field)
                fields.append(field)

        stage.duration_in_secs = sum([contest.duration_in_secs for contest in contests])
        if stage.duration_in_secs:
            time_elapsed = sum([contest.duration_in_secs for contest in contests if contest.is_over()])
            stage.info['_time_percentage'] = time_elapsed / stage.duration_in_secs
        else:
            stage.info.pop('_time_percentage', None)

        if field_to_problem:
            for stat in stage.statistics_set.all():
                problems = stat.addition.setdefault('problems', {})
                was_updated = False
                for k, v in list(stat.addition.items()):
                    match = re.search(field_to_problem['regex'], k)
                    if match:
                        problem_short = field_to_problem['format'].format(**match.groupdict())
                        if problem_short not in problems:
                            problems[problem_short] = {'result': v}
                        stat.addition.pop(k)
                        if 'fields_types' in stage.info:
                            stage.info['fields_types'].pop(k, None)
                        was_updated = True
                if was_updated:
                    stat.save(update_fields=['addition'])

        if parsed_statistic:
            for field in stage.info.setdefault('hidden_fields', []):
                if field not in hidden_fields:
                    hidden_fields.append(field)
        regex_hidden_fields = self.score_params.get('regex_hidden_fields')
        if regex_hidden_fields:
            for field in fields:
                if field not in hidden_fields and re.search(regex_hidden_fields, field):
                    hidden_fields.append(field)
        stage.info['fields'] = list(fields)
        stage.info['hidden_fields'] = hidden_fields

        fields_types = self.score_params.get('fields_types', {})
        if fields_types:
            stage.info.setdefault('fields_types', {}).update(fields_types)

        if not parsed_statistic:
            stage.statistics_set.exclude(pk__in=pks).delete()
            stage.n_statistics = len(results)
            stage.parsed_time = timezone_now

            standings_info = self.score_params.get('info', {})
            standings_info['fixed_fields'] = fixed_fields + [(f.lstrip('-'), f.lstrip('-')) for f in order_by]
            stage.info['standings'] = standings_info

            if divisions_order and self.score_params.get('divisions_ordering'):
                stage.info['divisions_order'] = divisions_order

            if stage.is_rated is None:
                stage.is_rated = False
        stage.save()
