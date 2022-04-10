from os import path

import httplib2
from googleapiclient.discovery import build
from oauth2client.file import Storage

DIR_NAME = path.dirname(path.abspath(__file__))
CODE_FILE = path.join(DIR_NAME, "code")
storage = Storage(path.join(DIR_NAME, "credentials"))
credentials = storage.get()
if credentials and credentials.access_token_expired:
    credentials.refresh(httplib2.Http())

assert credentials
http = credentials.authorize(httplib2.Http())
service = build('calendar', 'v3', http=http, cache_discovery=False)
