from submissions.models import Language, Submission, Testing, Verdict

from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(Language)
class LanguageAdmin(BaseModelAdmin):
    list_display = ['id', 'name', 'extensions']
    search_fields = ['id', 'name']


@admin_register(Verdict)
class VerdictAdmin(BaseModelAdmin):
    list_display = ['id', 'name', 'penalty', 'solved']
    search_fields = ['id', 'name']


@admin_register(Submission)
class SubmissionAdmin(BaseModelAdmin):
    list_display = ['id', 'account', 'problem_short', 'contest_time', 'language', 'verdict',
                    'failed_test', 'run_time', 'current_result', 'current_attempt', 'time',
                    'contest', 'statistic', 'problem', 'problem_key', 'secondary_key']
    search_fields = ['account__name', 'account__key', 'contest__title']
    list_filter = ['problem_short', 'problem_key', 'language', 'verdict']


@admin_register(Testing)
class TestingAdmin(BaseModelAdmin):
    list_display = ['id', 'submission', 'verdict', 'test_number', 'run_time',
                    'contest_time', 'time', 'secondary_key']
    list_filter = ['verdict']
