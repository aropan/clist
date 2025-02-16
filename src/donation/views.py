from django.shortcuts import render

from donation.models import DonationSource


def donate(request):
    sources = DonationSource.enabled.order_by('created')
    context = {
        'navbar_admin_model': DonationSource,
        'sources': sources,
    }
    return render(request, 'donate.html', context)
