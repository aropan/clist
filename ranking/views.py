from django.shortcuts import get_object_or_404, render
from django.utils.timezone import now

from ranking.models import Statistics
from true_coders.models import Party


def party_ranking(request, slug):
    party = get_object_or_404(Party.objects.for_user(request.user), slug=slug)
    contests = []
    results = []
    total = {}
    contest_set = party.rating_set.order_by('-contest__end_time')
    future = contest_set.filter(contest__start_time__gt=now())
    for r in contest_set.filter(contest__start_time__lt=now()):
        c = r.contest
        standings = [
            {
                'solving': s.solving,
                'upsolving': s.upsolving,
                'stat': s,
                'coder': coder,
            }
            for s in Statistics.objects.filter(
                account__coders__in=party.coders.all(), contest=c
            ).distinct()
            for coder in s.account.coders.all()
            if party.coders.filter(pk=coder.id).first()
        ]

        if standings:
            max_solving = max([s['solving'] for s in standings]) or 1
            max_total = max([s['solving'] + s['upsolving'] for s in standings]) or 1

            for s in standings:
                solving = s['solving']
                upsolving = s['upsolving']
                s['score'] = 4. * (solving + upsolving) / max_total + 1. * solving / max_solving

            max_score = max([s['score'] for s in standings]) or 1
            for s in standings:
                s['score'] = 100. * s['score'] / max_score

            standings.sort(key=lambda s: s['score'], reverse=True)

            for s in standings:
                coder = s['coder']
                d = total.setdefault(coder.id, {})
                d['score'] = s['score'] + d.get('score', 0)
                d['coder'] = coder

                d, s = d.setdefault('stat', {}), s['stat']

                solved = s.addition.get('solved', {})
                d['solving'] = solved.get('solving', s.solving) + d.get('solving', 0)
                d['upsolving'] = solved.get('upsolving', s.upsolving) + d.get('upsolving', 0)

        results.append(
            {
                'contest': c,
                'standings': standings,
            }
        )
        contests.append(c)

    total = sorted(list(total.values()), key=lambda d: d['score'], reverse=True)
    results.insert(0, {
        'standings': total,
    })

    for result in results:
        place = 0
        prev = None
        for i, s in enumerate(result['standings']):
            if prev != s['score']:
                prev = s['score']
                place = i + 1
            s['place'] = place

    return render(
        request,
        'party-ranking.html',
        {
            'future': future,
            'header': ['#', 'Coder', 'Score', 'Solving'],
            'party': party,
            'contests': contests,
            'results': results,
        },
    )
