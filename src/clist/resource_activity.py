import math
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count

from clist.models import Contest
from ranking.models import Account

HISTORY_DAYS = 1095
UPCOMING_DAYS = 30
CODER_ACTIVITY_DAYS = 365
SERIES_HALF_LIFE_DAYS = 180
SERIES_BONUS = 8
SCORE_SCALE = 20


def calculate_activity_scores(contests, linked_ids, major_series_ids, active_coders, now):
    monthly = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    series_bonuses = defaultdict(float)

    for contest in contests:
        resource_id = contest["resource_id"]
        end_time = contest["end_time"]
        age_days = max(0, (now - end_time).total_seconds() / 86400)
        major = contest["id"] in linked_ids or contest["series_id"] in major_series_ids

        if major:
            importance, half_life = 5, 730
        elif contest["is_promoted"]:
            importance, half_life = 3, 365
        elif contest["is_rated"]:
            importance, half_life = 1.5, 180
        else:
            importance, half_life = 1, 120

        statistics = min(max(contest["n_statistics"] or 0, 0), 10000)
        reach = 1 + 0.5 * math.log1p(statistics) / math.log1p(10000)
        upcoming = contest["start_time"] > now
        contribution = importance * reach * 2 ** (-age_days / half_life)
        if upcoming:
            contribution *= 0.5

        month_time = contest["start_time"] if upcoming else end_time
        month = monthly[resource_id][month_time.year, month_time.month]
        month[0] = max(month[0], contribution)
        month[1] += contribution

        if contest["series_id"] and (major or contest["is_promoted"]) and end_time <= now:
            bonus = SERIES_BONUS * 2 ** (-age_days / SERIES_HALF_LIFE_DAYS)
            series_bonuses[resource_id] = max(series_bonuses[resource_id], bonus)

    scores = {}
    for resource_id in monthly:
        contest_component = sum(
            strongest + 0.25 * math.log1p(total) for strongest, total in monthly[resource_id].values()
        )
        coder_count = active_coders.get(resource_id, 0)
        usage = min(1, math.log1p(coder_count) / math.log1p(5000))
        raw_score = contest_component * (1 + 0.25 * usage) + series_bonuses[resource_id]
        scores[resource_id] = min(100, max(0, -100 * math.expm1(-raw_score / SCORE_SCALE)))

    return scores


def get_resource_activity_scores(now):
    start = now - timedelta(days=HISTORY_DAYS)
    upcoming_end = now + timedelta(days=UPCOMING_DAYS)

    linked_ids = set()
    series_members = defaultdict(set)
    cphof_links = Contest.objects.filter(
        resource__host="cphof.org",
        related_id__isnull=False,
        end_time__gte=start,
        end_time__lte=upcoming_end,
    ).values_list("related_id", "related__series_id", "related__end_time", "related__invisible")
    for related_id, series_id, related_end, related_invisible in cphof_links:
        linked_ids.add(related_id)
        if series_id and not related_invisible and start <= related_end <= now:
            series_members[series_id].add(related_id)
    major_series_ids = {series_id for series_id, members in series_members.items() if len(members) >= 2}

    contests = (
        Contest.objects
        .filter(invisible=False, end_time__gte=start, start_time__lte=upcoming_end)
        .order_by()
        .values(
            "id",
            "resource_id",
            "start_time",
            "end_time",
            "n_statistics",
            "is_promoted",
            "is_rated",
            "series_id",
        )
        .iterator(chunk_size=2000)
    )
    active_coders = dict(
        Account.objects
        .filter(
            coders__user__isnull=False,
            coders__is_virtual=False,
            coders__last_activity__gte=now - timedelta(days=CODER_ACTIVITY_DAYS),
        )
        .order_by()
        .values("resource_id")
        .annotate(count=Count("coders", distinct=True))
        .values_list("resource_id", "count")
    )
    return calculate_activity_scores(contests, linked_ids, major_series_ids, active_coders, now)
