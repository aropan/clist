Contributing
======

* Clone fork with `--recursive`
* Install all requirements:
```
python3 -m venv environment
source environment/bin/activate
pip3 install -r requirements/requirements.txt
sudo ./requirements/packages.sh
```
* Copy config from template:
```
cp pyclist/conf.py.template pylcist/conf.py
```
* Enter all information in `pyclist/conf.py`
* Run `sudo ./requirements/configure.sh` to configure postgresql database
* Run `env DOMAIN=... PORT=... ./requirements/etc/generate.sh` to generate nginx and uwsgi configs
* Configure nginx by config file `requirements/etc/nginx/sites-enabled/clist`
* Configure uwsgin by config file `requirements/etc/uwsgi/apps-enabled/clist.ini`
