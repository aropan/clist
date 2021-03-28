Contributing
======

* Clone fork with `--recursive`

* Install all requirements:

```bash
cd clist
sudo ./requirements/packages.sh
python3 -m venv environment
source environment/bin/activate
pip3 install -r requirements/requirements.txt
```

* Copy config from template:

```bash
cp pyclist/conf.py.template pyclist/conf.py
```

* Enter all information in `pyclist/conf.py`

* Run `sudo ./requirements/configure.sh` to configure postgresql database

* Run `env DOMAIN=${DOMAIN} PORT=${PORT} ./requirements/etc/generate.sh` to generate nginx and uwsgi configs (example `env DOMAIN=clist.by PORT=80 ./requirements/etc/generate.sh`)

* Configure nginx by config file `requirements/etc/nginx/sites-enabled/clist`

* Configure uwsgi by config file `requirements/etc/uwsgi/apps-enabled/clist.ini`

* Run `./manage migrate` to migrate database

* Run `./manage createsuperuser` to create admin user

* Go to `${DOMAIN}/admin/true_coders/coder/` and create `Coder` for admin user
