### Run locally

You need `python3` (the fresher the better) and `docker` (wtih `docker-compose`).

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
