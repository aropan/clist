from django.test import TestCase

from clist.models import Resource
from ranking.models import Account
from ranking.utils import rename_account


class RenameAccountVerificationTest(TestCase):
    def test_verification_requirement_is_preserved_from_either_account(self):
        resource = Resource(host="rename-verification.example", url="https://rename-verification.example/", enable=True)
        Resource.objects.bulk_create([resource])

        for index, (old_required, new_required) in enumerate((
            (True, False),
            (False, True),
            (True, True),
            (False, False),
        )):
            with self.subTest(old_required=old_required, new_required=new_required):
                old = Account.objects.create(resource=resource, key=f"old-{index}", need_verification=old_required)
                new = Account.objects.create(resource=resource, key=f"new-{index}", need_verification=new_required)

                account = rename_account(old, new)

                account.refresh_from_db()
                assert account.need_verification == (old_required or new_required)
                assert not Account.objects.filter(resource=resource, key=f"old-{index}").exists()
                assert resource.accountrenaming_set.get(old_key=f"old-{index}").new_key == account.key
