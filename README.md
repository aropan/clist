Using Clist
======

First run
------

Before running server install all requirements:

    python3 -m venv clist_environment
    source env/bin/activate
    pip install -r requirements/requirements.txt
    sudo ./requirements/packages.sh

Now rename configs by:

    mv pyclist/conf.py.template pylcist/conf.py
    mv .pgpass.template .pgpass

Enter all information in configs

Now run configure script by:

    sudo ./requirements/configure.sh
