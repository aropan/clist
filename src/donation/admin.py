from typing import ClassVar

from donation.models import DonationSource
from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(DonationSource)
class DonationSourceAdmin(BaseModelAdmin):
    list_display: ClassVar = ["id", "name", "url", "enable"]
    search_fields: ClassVar = ["name", "url"]
