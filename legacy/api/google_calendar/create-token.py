#!/usr/bin/env python3

import conf

if __package__:
    from .auth import CODE_FILE, consume_authorization_code, create_flow, save_credentials
else:
    from auth import CODE_FILE, consume_authorization_code, create_flow, save_credentials


def main():
    flow = create_flow(conf.client_id, conf.client_secret)
    auth_uri, _ = flow.authorization_url(access_type="offline", prompt="consent")

    code = consume_authorization_code(CODE_FILE)

    if code:
        flow.fetch_token(code=code)
        save_credentials(flow.credentials)
    else:
        print(auth_uri)


if __name__ == "__main__":
    main()
