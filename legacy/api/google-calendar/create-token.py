#!/usr/bin/env python3

from oauth2client.client import OAuth2WebServerFlow
from oauth2client.file import Storage
from os import path, remove


def main():
    DIR_NAME = path.dirname(path.abspath(__file__))
    CODE_FILE = path.join(DIR_NAME, "code")
    storage = Storage(path.join(DIR_NAME, "credentials"))
    credentials = storage.get()

    with open(path.join(path.dirname(__file__), 'client_secret'), 'r') as fo:
        client_secret = fo.read().strip()

    flow = OAuth2WebServerFlow(
        client_id="47861026466-bv5lem6hchsi8ovk8nul45sr7b8d9i7n.apps.googleusercontent.com",
        client_secret=client_secret,
        scope="https://www.googleapis.com/auth/calendar",
        redirect_uri="https://legacy.clist.by/api/google-calendar/exchange-code.php",
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
