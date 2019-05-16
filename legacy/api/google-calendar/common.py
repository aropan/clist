from oauth2client.client import OAuth2WebServerFlow
from oauth2client.file import Storage
from os import path
from googleapiclient.discovery import build
import httplib2

DIR_NAME = path.dirname(path.abspath(__file__))
CODE_FILE = path.join(DIR_NAME, "code")
storage = Storage(path.join(DIR_NAME, "credentials"))
credentials = storage.get()
if credentials and credentials.access_token_expired:
    credentials.refresh(httplib2.Http())


def main():
    global credentials
    global storage

    flow = OAuth2WebServerFlow(
        client_id="47861026466-bv5lem6hchsi8ovk8nul45sr7b8d9i7n.apps.googleusercontent.com",
        client_secret="NQbOWUOuIL7nMBUKY3_Rk-z1",
        scope="https://www.googleapis.com/auth/calendar",
        redirect_uri="http://legacy.clist.by/api/google-calendar/exchange-code.php",
        access_type="offline",
        approval_prompt="force",
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
    else:
        print(auth_uri)


if __name__ == "__main__":
    main()


assert credentials
http = credentials.authorize(httplib2.Http())
service = build('calendar', 'v3', http=http)
