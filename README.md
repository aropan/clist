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
* Now run configure script by `sudo ./requirements/configure.sh`
