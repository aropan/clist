from django.test import SimpleTestCase
from rq.job import validate_job_id

from utils.rq import get_resource_job_id


class GetResourceJobIdTest(SimpleTestCase):

    def test_dotted_host_is_valid_job_id(self):
        job_id = get_resource_job_id('parse_statistics', 'codeforces.com')
        validate_job_id(job_id)
        assert job_id == 'parse_statistics_codeforces-com'

    def test_host_with_path_is_valid_job_id(self):
        job_id = get_resource_job_id('parse_accounts', 'nerc.itmo.ru/school')
        validate_job_id(job_id)
        assert job_id == 'parse_accounts_nerc-itmo-ru-school'
