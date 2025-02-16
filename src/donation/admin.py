from donation.models import DonationSource

from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(DonationSource)
class DonationSourceAdmin(BaseModelAdmin):
    list_display = ['id', 'name', 'url', 'enable']
    search_fields = ['name', 'url']
