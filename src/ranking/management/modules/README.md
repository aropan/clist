## conf.py

The ignored `conf.py` supplies credentials used by parsers such as
`codeforces.py` and `codechef.py`. Create it locally when needed;
`configure.py` does not generate it. Never put real credentials in this
README, a parser fixture, or a commit. The parsers currently use fields like:

```python
CODEFORCES_API_KEYS = {
    '{username_1}': (
        '{key_1}',
        '{secret_1}',
    ),
    '{username_2}': (
        '{key_2}',
        '{secret_2}',
    ),
    '{username_n}': (
        '{key_n}',
        '{secret_n}',
    ),
    '__default__': '{username_i}',
}

CODECHEF_USERNAME = '{username}'
CODECHEF_PASSWORD = '{password}'
```
