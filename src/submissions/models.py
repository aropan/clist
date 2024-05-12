from typing import Optional

from django.db import models
from django.db.models import Q

from clist.models import Problem
from pyclist.models import BaseModel
from ranking.models import Account, Contest, Statistics
from utils.timetools import timed_cache


class Language(BaseModel):
    id = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=50, db_index=True)
    extensions = models.JSONField(default=list, blank=True)

    @staticmethod
    def get(language) -> Optional['Language']:
        try:
            return Language.objects.get(Q(id__iexact=language) | Q(name__iexact=language))
        except Language.DoesNotExist:
            return None

    @staticmethod
    @timed_cache('15m')
    def cached_get(language) -> Optional['Language']:
        return Language.get(language)

    def __str__(self):
        return f'Language#{self.id}'


class Verdict(BaseModel):
    id = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=50, db_index=True)
    penalty = models.BooleanField(default=True)
    solved = models.BooleanField(default=False)

    @staticmethod
    def get(verdict) -> Optional['Verdict']:
        try:
            return Verdict.objects.get(Q(id__iexact=verdict) | Q(name__iexact=verdict))
        except Verdict.DoesNotExist:
            return None

    @staticmethod
    @timed_cache('15m')
    def cached_get(verdict) -> Optional['Verdict']:
        return Verdict.get(verdict)

    def __str__(self):
        return f'Verdict#{self.id}'


class Submission(BaseModel):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='submissions')
    contest = models.ForeignKey(Contest, on_delete=models.CASCADE, related_name='submissions')
    problem = models.ForeignKey(Problem, on_delete=models.SET_NULL, related_name='submissions',
                                default=None, null=True, blank=True)
    statistic = models.ForeignKey(Statistics, on_delete=models.CASCADE, related_name='submissions')
    secondary_key = models.CharField(max_length=50)
    problem_short = models.CharField(max_length=50, db_index=True)
    problem_key = models.CharField(max_length=50, db_index=True)
    contest_time = models.DurationField(db_index=True)
    current_result = models.CharField(max_length=20, default=None, null=True, blank=True)
    current_attempt = models.IntegerField(default=None, null=True, blank=True)
    language = models.ForeignKey(Language, on_delete=models.PROTECT)
    verdict = models.ForeignKey(Verdict, on_delete=models.PROTECT)
    run_time = models.FloatField(default=None, null=True, blank=True, db_index=True)
    failed_test = models.IntegerField(default=None, null=True, blank=True, db_index=True)
    time = models.DateTimeField(default=None, null=True, blank=True)

    class Meta:
        unique_together = ('statistic', 'secondary_key', 'problem_short')

        indexes = [
            models.Index(fields=['contest', 'contest_time']),
            models.Index(fields=['contest', '-contest_time']),
            models.Index(fields=['contest', 'account', 'contest_time']),
            models.Index(fields=['contest', 'account', '-contest_time']),
            models.Index(fields=['contest', 'problem_short', 'contest_time']),
            models.Index(fields=['contest', 'problem_short', '-contest_time']),
            models.Index(fields=['contest', 'account', 'problem_short', 'contest_time']),
            models.Index(fields=['contest', 'account', 'problem_short', '-contest_time']),
        ]

    @property
    def problem_index(self):
        return self.problem_key or self.problem_short

    def __str__(self):
        return f'Submission#{self.id}'


class Testing(BaseModel):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='tests')
    verdict = models.ForeignKey(Verdict, on_delete=models.PROTECT)
    secondary_key = models.CharField(max_length=50)
    test_number = models.IntegerField(default=None, null=True, blank=True, db_index=True)
    run_time = models.FloatField(default=None, null=True, blank=True, db_index=True)
    contest_time = models.DurationField(default=None, null=True, blank=True)
    time = models.DateTimeField(default=None, null=True, blank=True)

    class Meta:
        unique_together = ('submission', 'secondary_key')

    def __str__(self):
        return f'Testing#{self.id}'
