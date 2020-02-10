Contributing
======

* Clone fork and clone with `--recursive`
* Install all requirements:
```
python3 -m venv environment
source environment/bin/activate
pip install -r requirements/requirements.txt
sudo ./requirements/packages.sh
```
* Copy config from tempalte:
```
cp pyclist/conf.py.template pylcist/conf.py
```
* Enter all information in `pylcist/conf.py`
* Now run configure script by `sudo ./requirements/configure.sh`
