#!/usr/bin/env python3

import os

import yaml

from utils.requester import requester


def get_auth():
    dirname = os.path.dirname(__file__)
    with open(os.path.join(dirname, 'auth.yaml'), 'r') as fo:
        return yaml.safe_load(fo)


def change_names(contest_id, names):
    auth = get_auth()

    with requester(
        cookie_filename=os.path.join(os.path.dirname(__file__), 'cookies', auth['username'] + '.cookie'),
        caching=False,
    ) as req:
        url = f'https://contest.yandex.ru/admin/contest-participants?contestId={contest_id}&forceOldPages=true'
        page = req.get(url)

        # auth
        form = req.form(action=None, limit=1)
        if form and form['method'] == 'post' and 'login' in form['post'] and 'retpath' in form['post']:
            page = req.submit_form(
                form=form,
                data={'login': auth['username'], 'passwd': auth['password']},
                url='https://passport.yandex.ru/auth/',
            )

        form = req.form(action=None, fid='change-displayed-names-form', enctype=True)
        names = '\n'.join(f'''{r['login']} {r['name']}''' for r in names)

        page = req.submit_form(
            form=form,
            data={'names': names, 'files__': {'file': {'filename': 'file', 'content': ''}}},
            url='https://contest.yandex.ru/admin/contest-participants/change-names',
        )
        return page
