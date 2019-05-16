# -*- coding: utf-8 -*-

from common import requester

import re
import json

req = requester.requester()


def getinfo(url, key=None):
    match = re.search(r'\/(?P<cid>[^\/]*)$', url)
    if not match:
        return
    return {
        'cid': match.group('cid'),
        'url': url,
    }


def getresult(info, user):
    if not user:
        return
    if 'cid' not in info:
        return
    if 'url' not in info:
        return

    global req
    url = "https://www.hackerrank.com/rest/contests/%(cid)s/challenges" % info
    page = req.get(url)
    r = {
        'score': 0,
        'submissions': 0,
        'points': 0,
    }
    for task in json.loads(page)['models']:
        max_score = False
        if 'max_score' in task:
            max_score = task['max_score']
            url = "https://www.hackerrank.com/rest/contests/%(contest_slug)s/challenges/%(slug)s/leaderboard/filter?country=Belarus&filter_kinds=country&offset=0&limit=%(total_count)s&include_practice=true" % task  # noqa
        else:
            max_score = False
            url = "https://www.hackerrank.com/rest/contests/%(contest_slug)s/challenges/%(slug)s/leaderboard?offset=0&limit=%(total_count)s&include_practice=true" % task  # noqa
        page = req.get(url)
        if req.error:
            continue
        for member in json.loads(page)['models']:
            if not max_score:
                max_score = member['score']
            if member['hacker'] == user:
                r['submissions'] += 1
                r['score'] += 1 if max_score * 0.7 < member['score'] else 0
                r['points'] += member['score']
    if not r['submissions']:
        return
    r['url'] = info['url']
    r['addition'] = ['points', 'score', 'submissions']
    return r


if __name__ == "__main__":
    print(getresult(getinfo("https://www.hackerrank.com/contests/w3", "920"), "primorial"))
