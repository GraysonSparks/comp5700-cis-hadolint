# Fallback Dockerfiles

`cisdiff` scans these files only if it cannot find the course `dockerfiles.zip`.
The course file is on an Auburn SharePoint site that the student and the TA cannot open.
If you give `--dockerfiles`, or a `dockerfiles.zip` is in the current folder, the tool does not use these files.

All files are copied without changes from public repositories with permissive licenses.
They were downloaded on 2026-11-09.

| Folder | Source (repository / path) | Commit | License |
|---|---|---|---|
| `python` | docker-library/python `3.12/slim-bookworm/Dockerfile` | `f4c67ece208d` | MIT |
| `node` | nodejs/docker-node `22/bookworm-slim/Dockerfile` | `e6e3364fa7ec` | MIT |
| `nginx` | nginxinc/docker-nginx `mainline/debian/Dockerfile` | `d99174e2cecf` | BSD-2-Clause |
| `postgres` | docker-library/postgres `17/bookworm/Dockerfile` | `dfc76bb299b0` | MIT |
| `redis` | docker-library/redis `7.4/debian/Dockerfile` | `30e7d6b51c8e` | BSD-3-Clause |
| `httpd` | docker-library/httpd `2.4/Dockerfile` | `2d12c5e41d57` | Apache-2.0 |
| `ruby` | docker-library/ruby `3.3/bookworm/Dockerfile` | `52052d14fd1f` | BSD-2-Clause |
| `php` | docker-library/php `8.3/bookworm/apache/Dockerfile` | `edf9e4989956` | MIT |
| `jupyter-base` | jupyter/docker-stacks `images/base-notebook/Dockerfile` | `90b46d6b8248` | BSD-3-Clause |
| `traefik` | traefik/traefik `Dockerfile` | `2bcd3a8cc325` | MIT |
| `ac-flask` | docker/awesome-compose `flask/app/Dockerfile` | `30f4b7f6a6c3` | CC0-1.0 |
| `ac-django` | docker/awesome-compose `django/app/Dockerfile` | `30f4b7f6a6c3` | CC0-1.0 |
| `ac-react-express` | docker/awesome-compose `react-express-mongodb/backend/Dockerfile` | `30f4b7f6a6c3` | CC0-1.0 |
| `ac-spring` | docker/awesome-compose `spring-postgres/backend/Dockerfile` | `30f4b7f6a6c3` | CC0-1.0 |
| `ac-nginx-golang` | docker/awesome-compose `nginx-golang/backend/Dockerfile` | `30f4b7f6a6c3` | CC0-1.0 |
| `ac-react-java` | docker/awesome-compose `react-java-mysql/frontend/Dockerfile` | `30f4b7f6a6c3` | CC0-1.0 |
| `ac-angular` | docker/awesome-compose `angular/angular/Dockerfile` | `30f4b7f6a6c3` | CC0-1.0 |
| `ac-vuejs` | docker/awesome-compose `vuejs/vuejs/Dockerfile` | `30f4b7f6a6c3` | CC0-1.0 |
| `ac-fastapi` | docker/awesome-compose `fastapi/Dockerfile` | `30f4b7f6a6c3` | CC0-1.0 |

The official images (first 10 rows) are well maintained and give few findings.
The awesome-compose samples (`ac-*`) are short example projects and give more findings.
