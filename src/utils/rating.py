#!/usr/bin/env python3


from datetime import datetime, timedelta

from pytz import utc


def get_n_contests_weight(n_contests):
    return 1 - 0.9 ** n_contests


def get_last_activity_weight(last_activity, base=None):
    if not last_activity:
        return 0
    base = base or datetime.now(utc)
    n_activities = (base - last_activity) / timedelta(days=180)
    return 0.9 ** max(n_activities, 0)


def get_weighted_rating(wratings, target, threshold=0.95, cache=None) -> float:
    left = 0
    right = 5000

    for _ in range(14):
        middle = (left + right) / 2

        if cache is not None and middle in cache:
            e_total, weight_sum, positive_prob, negative_prob = cache[middle]
        else:
            e_total = 0
            weight_sum = 0
            positive_prob = 1
            negative_prob = 1
            for weight, rating in wratings:
                exp = (middle - rating) / 400
                e = 1 / (1 + 10 ** exp)
                weight_sum += weight
                e_total += weight * e
                positive_prob *= e
                negative_prob *= 1 - e
            if cache is not None:
                cache[middle] = e_total, weight_sum, positive_prob, negative_prob

        """
        Chmel_Tolstiy proposed for special case:
        * the maximum rating, in which everything will be solved with a probability of >= X%
        * the minimum rating of the problem, in which no one will solve with a probability of >= X%
        """
        if threshold and positive_prob > threshold:
            left = middle
        elif threshold and negative_prob > threshold:
            right = middle
        elif e_total < target:
            right = middle
        else:
            left = middle
    rating = (left + right) / 2
    return rating


def get_rating(ratings) -> float:
    wratings = [(1, r) for r in ratings]
    return get_weighted_rating(wratings, 0.5)
