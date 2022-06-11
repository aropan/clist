#!/usr/bin/env python3

from os import path, remove

import conf
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.file import Storage


def main():
    DIR_NAME = path.dirname(path.abspath(__file__))
    CODE_FILE = path.join(DIR_NAME, "code")
    storage = Storage(path.join(DIR_NAME, "credentials"))
    credentials = storage.get()

    flow = OAuth2WebServerFlow(
        client_id=conf.client_id,
        client_secret=conf.client_secret,
        scope="https://www.googleapis.com/auth/calendar",
        redirect_uri="https://legacy.clist.by/api/google_calendar/exchange-code.php",
        access_type="offline",
        prompt="consent",
    )
    auth_uri = flow.step1_get_authorize_url()

    code = None
    if path.exists(CODE_FILE):
        with open(CODE_FILE, "r") as fo:
            code = fo.read().strip()
        open(CODE_FILE, "w").close()

    if code:
        credentials = flow.step2_exchange(code)
        storage.put(credentials)
        remove(CODE_FILE)
    else:
        print(auth_uri)


if __name__ == "__main__":
    main()
