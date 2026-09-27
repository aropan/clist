## Local settings

`configure.py` creates the ignored `conf.py` from
[`conf.py.template`](conf.py.template). Keep real credentials out of Git.
Database connection settings come from `.env.db` through the `db_conf`
Docker secret, as read by [`settings.py`](settings.py). The
`src/.env.dev` and `src/.env.prod` files select environment-specific
application settings.
