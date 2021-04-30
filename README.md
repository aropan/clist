Contributing
======

* Clone fork with `--recursive`:
```bash
git clone --recursive git@github.com:aropan/clist.git
cd clist
```

* Install packages `sudo ./requirements/packages.sh`

* Configure and activate virtualenv:
```bash
python3 -m venv .envs/clist
source .envs/clist/bin/activate
```

* Install requirements `pip3 install -r requirements/requirements.txt`

* Copy config from template `cp pyclist/conf.py.template pyclist/conf.py` and enter all information in `pyclist/conf.py`:

* Run `sudo ./requirements/configure.sh` to configure postgresql database

* Run `env DOMAIN=${DOMAIN} PORT=${PORT} ./requirements/etc/generate.sh` to generate nginx and uwsgi configs (example `env DOMAIN=clist.by PORT=80 ./requirements/etc/generate.sh`)

* Configure nginx by config file `requirements/etc/nginx/sites-enabled/clist`

* Configure uwsgi by config file `requirements/etc/uwsgi/apps-enabled/clist.ini`

* Run `./manage.py migrate` to migrate database

* Run `./manage.py createsuperuser` to create admin user

* Go to `${DOMAIN}/admin/true_coders/coder/` and create `Coder` for admin user
