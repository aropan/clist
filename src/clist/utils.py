#!/usr/bin/env python3

from django.urls import reverse


def update_accounts_by_coders(accounts):
    accounts = accounts.prefetch_related('coders').select_related('resource')
    for account in accounts:
        update_account_by_coders(account)


def update_account_by_coders(account):
    url = False
    custom_countries = None
    for coder in account.coders.all():
        if url:
            url = True
        else:
            url = reverse('coder:profile', args=[coder.username]) + f'?search=resource:{account.resource.host}'

        coder_custom_countries = coder.settings.get('custom_countries', {})
        if custom_countries is None:
            custom_countries = coder_custom_countries
        else:
            custom_countries = dict(
                set(custom_countries.items()) &
                set(coder_custom_countries.items())
            )
            if not custom_countries:
                break

    if isinstance(url, bool):
        url = account.account_default_url()

    update_fields = []

    if url != account.url:
        account.url = url
        update_fields.append('url')

    custom_countries = custom_countries or {}
    if custom_countries != account.info.get('custom_countries_', {}):
        account.info['custom_countries_'] = custom_countries
        update_fields.append('info')

    if update_fields:
        account.save(update_fields=update_fields)
