Contributing
======

* Clone fork with `--recursive`
* Install all requirements:
```
sudo ./requirements/packages.sh
python3 -m venv environment
source environment/bin/activate
pip3 install wheel
pip3 install -r requirements/requirements.txt
```
* Copy config from tempalte:
```
cp pyclist/conf.py.template pylcist/conf.py
```
* Enter all information in `pylcist/conf.py`
* Now run configure script by `sudo ./requirements/configure.sh`
