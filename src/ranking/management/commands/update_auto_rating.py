#!/usr/bin/env python3

import tqdm
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import OuterRef, Exists

from clist.models import Contest
from ranking.models import AutoRating, Rating


class Command(BaseCommand):
    help = 'Auto rating'

    def handle(self, *args, **options):

        qs = AutoRating.objects.filter(deadline__gt=timezone.now())
        qs = qs.select_related('party')
        qs = qs.prefetch_related('party__rating_set')
        for auto_rating in tqdm.tqdm(qs, desc='update auto rating'):
            party = auto_rating.party
            contests = Contest.objects.filter(**auto_rating.info['filter'])

            party_contests = party.rating_set.filter(contest_id=OuterRef('pk'))
            contests = contests.annotate(in_party=Exists(party_contests)).filter(in_party=False)

            for contest in contests:
                rating = Rating(party=party, contest=contest)
                rating.save()
