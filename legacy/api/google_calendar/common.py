from googleapiclient.discovery import build

if __package__:
    from .auth import load_credentials
else:
    from auth import load_credentials

credentials = load_credentials()
service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
