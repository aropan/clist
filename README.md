### Run locally

You need `python3` (more fresher is better, tested on 3.10) and `docker` (with `docker-compose` v2).

* Clone fork with `--recursive`:
```
git clone --recursive git@github.com:aropan/clist.git
cd clist
```

* Set default variables and build dev container (you can always press Enter and leave the defaults as they are):
```
python3 ./configure.py
```

* Run dev container:
```
docker-compose up --build dev
```

* Open [http://localhost:10042/](http://localhost:10042/) and enjoy.
