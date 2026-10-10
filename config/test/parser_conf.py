# Synthetic parser credentials for the isolated test stack (docker-compose.test.yml),
# mounted over the gitignored ranking/management/modules/conf.py.
# Every value is fake: hosts use the reserved .invalid TLD and nothing here is a real credential.

ATCODER_HANDLE = "clist-test"
ATCODER_PASSWORD = "synthetic-test-password"

BESTCODER_AUTHORID = "clist-test"
BESTCODER_PASSWORD = "synthetic-test-password"

CHALLENGES_REPLY_EMAIL = "parser@clist.invalid"
CHALLENGES_REPLY_PASSWORD = "synthetic-test-password"

CODECHEF_USERNAME = "clist-test"
CODECHEF_PASSWORD = "synthetic-test-password"

CODEFORCES_API_KEYS = {
    "__default__": "default",
    "default": ("synthetic-test-key", "synthetic-test-secret"),
}

CUPS_EMAIL = "parser@clist.invalid"
CUPS_PASSWORD = "synthetic-test-password"

DLGSU_ID = "clist-test"
DLGSU_PASSWORD = "synthetic-test-password"

GEEKSFORGEEKS_USERNAME = "clist-test"
GEEKSFORGEEKS_PASSWORD = "synthetic-test-password"

HACKEREARTH_USERNAME = "clist-test"
HACKEREARTH_PASSWORD = "synthetic-test-password"

PROJECTEULER_USERNAME = "clist-test"
PROJECTEULER_PASSWORD = "synthetic-test-password"

TOPCODER_HANDLE = "clist-test"
TOPCODER_PASSWORD = "synthetic-test-password"
TOPCODER_API_MM_URL_FORMAT = "https://api.topcoder.invalid/challenges/{}"

UOJ_USERNAME = "clist-test"
UOJ_PASSWORD = "synthetic-test-password"
