import re

import django_rq
import flag
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db.models import Q
from django.urls import reverse

from clist.templatetags.extras import (as_number, get_division_problems, get_problem_name, get_problem_short, is_hidden,
                                       is_partial, is_solved, md_escape, md_url, md_url_text, scoreformat,
                                       solution_time_compare)


def compose_message_by_problems(
    problem_shorts,
    statistic,
    previous_addition,
    contest_or_problems,
    subscription=None,
    general_message=None,
):
    with_subscription_names = (
        subscription
        and subscription.with_custom_names
        and subscription.coder_list
        and subscription.coder_list.with_names
    )
    if general_message is not None and not with_subscription_names:
        return general_message

    problems = statistic.addition.get('problems', {})
    previous_problems = previous_addition.get('problems', {})

    contest_problems = get_division_problems(contest_or_problems, statistic.addition)
    contest_problems = {get_problem_short(problem): problem for problem in contest_problems}

    problem_messages = []
    max_time_solution = None
    is_improving = False

    if problem_shorts == 'all':
        problem_shorts = list(problems.keys())
    else:
        for short, solution in problems.items():
            if short in problem_shorts or not is_hidden(solution):
                continue
            problem_shorts.append(short)

    for short in problem_shorts:
        solution = problems.get(short, {})
        previous_problem = previous_problems.get(short, {})

        result = solution.get('result')
        verdict = solution.get('verdict')
        previous_result = previous_problem.get('result')

        is_solved_result = is_solved(solution)
        is_improving |= is_solved_result

        contest_problem = contest_problems.get(short, {})
        problem_message = short if 'short' in contest_problem else get_problem_name(contest_problem)
        problem_message = md_escape(problem_message)
        if re.match(r'^[\w\d_]+$', problem_message):
            problem_message = f'#{problem_message}'
        if 'name' in solution:
            problem_message = '%s. %s' % (problem_message, md_escape(solution['name']))
        problem_message = '%s `%s`' % (problem_message, scoreformat(result, with_shorten=False))
        if not is_solved_result and verdict:
            problem_message = '%s %s' % (problem_message, md_escape(verdict))

        if previous_result and is_partial(solution):
            delta = as_number(result, default=0) - as_number(previous_result, default=0)
            is_improving |= delta > 0
            problem_message += " `%s%s`" % ('+' if delta >= 0 else '', delta)

        if max_time_solution is None or solution_time_compare(max_time_solution, solution) < 0:
            max_time_solution = solution

        if solution.get('first_ac'):
            problem_message += ' FIRST ACCEPTED'
        if solution.get('is_max_score'):
            problem_message += ' MAX SCORE'
        if solution.get('try_first_ac'):
            problem_message += ' TRY FIRST AC'
        problem_messages.append(problem_message)
    problem_message = '(%s)' % ', '.join(problem_messages) if problem_messages else ''
    time_message = '`[%s]`' % max_time_solution["time"] if max_time_solution and 'time' in max_time_solution else ''

    previous_place = previous_addition.get('place')
    previous_solving = previous_addition.get('score')
    has_solving_diff = previous_solving is None or previous_solving != statistic.solving
    place_message = statistic.place
    if previous_place and has_solving_diff:
        place_message = '%s->%s' % (previous_place, statistic.place)

    standings_url = reverse('ranking:standings_by_id', args=[statistic.contest_id]) + f'?find_me={statistic.pk}'
    account_name = statistic.account_name
    if with_subscription_names:
        groups = subscription.coder_list.groups.filter(name__isnull=False)
        groups = groups.filter(Q(values__account=statistic.account) |
                               Q(values__coder__account=statistic.account))
        group = groups.first()
        if group:
            account_name = group.name
    account_message = '[%s](%s)' % (md_url_text(account_name), md_url(standings_url))
    if statistic.account.country:
        account_message = flag.flag(statistic.account.country.code) + account_message

    suffix_message = ''
    if has_solving_diff:
        suffix_message += f'= `{scoreformat(statistic.solving, with_shorten=False)}`'
        if 'penalty' in statistic.addition:
            suffix_message += rf' `[{statistic.addition["penalty"]}]`'
    message = f'{time_message} `{place_message}`. {account_message} {suffix_message} {problem_message}'.strip()
    message = re.sub(r'(\s)\s+', r'\1', message)
    return message


def send_messages(**kwargs):
    if settings.DEBUG:
        admin_coders = list(User.objects.filter(is_superuser=True).values_list('username', flat=True))
        kwargs.setdefault('coders', []).extend(admin_coders)
    django_rq.get_queue('system').enqueue(call_command, 'sendout_tasks', **kwargs)
