# CLIST

> **CLIST** is your comprehensive guide to global programming contests. It aggregates upcoming programming contests from various websites, allowing you to track competitive programming events and coding challenges.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Development Setup](#development-setup)
  - [1. Fork the Repository](#1-fork-the-repository)
  - [2. Clone Your Fork](#2-clone-your-fork)
  - [3. Run `configure.py`](#3-run-configurepy)
  - [4. Start the Development Container](#4-start-the-development-container)
  - [5. Access the Application](#5-access-the-application)
- [Contributing](#contributing)

---

## Prerequisites

- [Python 3.10](https://www.python.org/downloads/)
- [Docker (with Docker Compose v2)](https://www.docker.com/products/docker-desktop)

---

## Development Setup

### 1. Fork the Repository

If you plan to contribute changes, first **fork** this repository on GitHub. Otherwise, you can simply clone the main repository directly (see step 2).

### 2. Clone Your Fork

Make sure to include the `--recursive` flag to clone any submodules:

```
git clone --recursive https://github.com/<your-username>/clist.git
```

Then change to the project directory:

```
cd clist
```

### 3. Run `configure.py`

This script sets up default environment variables. You can usually press Enter to accept the defaults:

```
python3 ./configure.py
```

### 4. Start the Development Container

Use Docker Compose to build and run the development container:

```
docker compose up --build dev
```

### 5. Access the Application

Open your web browser and go to [http://localhost:10042/](http://localhost:10042/) to start using the application.

---

## Contributing

1. **Create a new branch** for your feature or fix:
   ```
   git checkout -b my-new-feature
   ```
2. **Commit your changes**:
   ```
   git commit -m "Add some feature"
   ```
3. **Push to the branch**:
   ```
   git push origin my-new-feature
   ```
4. **Open a Pull Request** on GitHub to merge your changes back into the main repository.

> **Note**: We appreciate any contributions—whether it’s improving the code, documentation, or other parts of the project!
