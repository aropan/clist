Contributing
======

* Clone fork with `--recursive`
* Install all requirements:
```
sudo ./requirements/packages.sh
python3 -m venv environment
source environment/bin/activate
pip3 install -r requirements/requirements.txt
```
* Copy config from template:
```
cp pyclist/conf.py.template pylcist/conf.py
```
* Enter all information in `pyclist/conf.py`
* Run `sudo ./requirements/configure.sh` to configure postgresql database
* Run `env DOMAIN=${DOMAIN} PORT=${PORT} ./requirements/etc/generate.sh` to generate nginx and uwsgi configs (example `env DOMAIN=clist.by PORT=80 ./requirements/etc/generate.sh`)
* Configure nginx by config file `requirements/etc/nginx/sites-enabled/clist`
* Configure uwsgin by config file `requirements/etc/uwsgi/apps-enabled/clist.ini`
