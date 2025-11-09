import re
from collections import OrderedDict, defaultdict

import arrow
import django_rq
import flag
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import reverse
from django.utils import translation

from clist.templatetags.extras import (as_number, get_division_problems, get_problem_hash, get_problem_name,
                                       get_problem_short, get_problem_title, get_problem_url, is_hidden, is_partial,
                                       is_solved, md_escape, md_url, md_url_text, scoreformat, solution_time_compare)
from utils.translation import localize_data


def lazy_compose_message(func):

    def wrapper(*args, subscription=None, general_message=None, cache=None, **kwargs):
        if cache is not None and subscription is not None:
            cache_key = subscription.notification_key
            if cache_key in cache:
                return
            cache.add(cache_key)

        with_subscription_names = subscription and subscription.with_coder_list_names
        if general_message is not None and not with_subscription_names:
            return general_message
        locale = getattr(subscription, 'locale', None) or translation.get_language()
        with translation.override(locale):
            return func(*args, subscription=subscription, locale=locale, **kwargs)

    return wrapper


@lazy_compose_message
def compose_message_by_problems(
    problem_shorts,
    statistic,
    previous_addition,
    contest_or_problems,
    subscription,
    locale,
):
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
    if subscription and (name := subscription.account_name(statistic.account)):
        account_name = name
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


@lazy_compose_message
def compose_message_by_submissions(resource, account, submissions, subscription, locale) -> str | None:
    contest_problems = OrderedDict()
    for submission in submissions:
        contest = submission['contest']
        problem = submission['problem']
        info = submission['info']
        if subscription and subscription.contest_id and subscription.contest_id != contest.id:
            continue
        problem_key = get_problem_hash(contest, problem)
        problems = contest_problems.setdefault(contest, OrderedDict())

        if problem_key not in problems:
            localize_data(problem, locale)
            problems[problem_key] = {
                'problem': problem,
                'submissions': [],
            }
        problems[problem_key]['submissions'].append(info)
    if not contest_problems:
        return

    account_name = account.short_display(resource=resource)
    if subscription and (name := subscription.account_name(account)):
        account_name = name
    account_message = '[%s](%s)' % (md_url_text(account_name), md_url(account.url))
    messages = [account_message]
    limit = 5

    def get_verdicts_message(verdicts):
        return ', '.join([f'`{k}`x{v}' if v > 1 else f'`{k}`' for k, v in verdicts.items()])

    def get_time_ago_message(submission):
        if 'submission_time' in submission:
            time = submission['submission_time']
            time_ago = arrow.get(time).humanize(locale=locale)
        else:
            time_ago = str(submission['submission_id'])
        if 'url' in submission:
            time_ago = '[%s](%s)' % (md_url_text(time_ago), md_url(submission['url']))
        return time_ago

    more_verdicts = defaultdict(int)
    more_problems = 0
    more_contests = 0
    index = 0
    for contest, problems in contest_problems.items():
        if index < limit:
            messages.append(md_escape(contest.title))
        else:
            more_contests += 1
        for problem_key, problem_submissions in problems.items():
            index += 1
            problem = problem_submissions['problem']
            submissions = problem_submissions['submissions']
            last_submission = submissions[0]

            if index > limit:
                for submission in submissions:
                    more_verdicts[submission['verdict']] += 1
                more_problems += 1
                continue

            verdicts = defaultdict(int)
            for submission in submissions:
                verdicts[submission['verdict']] += 1

            problem_message = get_problem_title(problem)
            if url := get_problem_url(problem):
                problem_message = '[%s](%s)' % (md_url_text(problem_message), md_url(url))
            else:
                problem_message = '`%s`' % md_escape(problem_message)
            problem_message = '%s = %s' % (problem_message, get_verdicts_message(verdicts))
            problem_message = '%s. %s' % (problem_message, get_time_ago_message(last_submission))
            messages.append(problem_message)

    if more_contests or more_problems or more_verdicts:
        message = f"and {more_problems} more problems"
        if more_contests:
            message += f" ({more_contests} contests)"
        message += f" = {get_verdicts_message(more_verdicts)}"
        messages.append(message)

    return '\n'.join(messages)


def send_messages(**kwargs):
    if settings.DEBUG:
        admin_coders = list(User.objects.filter(is_superuser=True).values_list('username', flat=True))
        kwargs.setdefault('coders', []).extend(admin_coders)
    django_rq.get_queue('system').enqueue(call_command, 'sendout_tasks', **kwargs)
