## Prerequisites

- [Python 3 (version 3.10 or later)](https://www.python.org/downloads/) 
- [Docker (with Docker Compose v2)] (https://www.docker.com/products/docker-desktop/)

## Setup 

1. Clone repository
You need to clone the forked repository with all its submodules therfore use --recursive:
```
git clone --recursive https://github.com/userName/clist.git
```
2. Change to `clist` Directory
``` 
cd clist 
```
3. Set Default Variables and Build Dev Container :
Run the configure.py script to set up default variables. You can usually press Enter to accept the default values:
```
python3 ./configure.py
```
4. Run the Development Container:
Use Docker Compose to build and run the development container:
```
docker compose up --build dev
```
If you are using Mac and if you are getting error `docker-compose not found` then try using below command first
```
brew install docker-compose
```
5. Access the Application:Open your web browser and navigate to http://localhost:10042/ to start using the application.

## Contributing

1. Fork it And clone it.
2. Create your feature branch: ```git checkout -b my-new-feature```
3. Commit your changes: ```git commit -m 'Add some feature’```
4. Push to the branch: ```git push origin my-new-feature```
5. Submit a pull request :D