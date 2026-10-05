# Django Docker Production

This project runs a Django application with Docker Compose, Gunicorn, Nginx, and MySQL.

## Architecture

```text
Browser
   |
   | http://localhost:8081
   v
Nginx container
   |
   | forwards dynamic requests to django:8000
   v
Django/Gunicorn container
   |
   | database connection
   v
MySQL container
```

Nginx and Django communicate through a private Docker network. Only Nginx is
published to the host.

## DevOps files

### `compose.yaml`

`compose.yaml` defines the complete container stack:

- `mysql`: MySQL 8.4 database.
- `django`: Django application built from `app/Dockerfile`.
- `nginx`: Nginx reverse proxy and static-file server.

### MySQL service

```yaml
mysql:
  image: mysql:8.4
```

Database values are read from environment variables:

```yaml
environment:
  MYSQL_DATABASE: ${DB_NAME}
  MYSQL_USER: ${DB_USER}
  MYSQL_PASSWORD: ${DB_PASSWORD}
  MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASSWORD}
```

The `--env-file app/.env` option is required when running Compose from the
repository root because these `${...}` values are resolved by Compose itself.

MySQL data is stored in the persistent `mysql_data` volume:

```yaml
volumes:
  - mysql_data:/var/lib/mysql
```

The health check waits for MySQL to accept connections:

```yaml
healthcheck:
  test:
    [
      "CMD",
      "mysqladmin",
      "ping",
      "-h",
      "localhost",
      "-u",
      "root",
      "-p${DB_ROOT_PASSWORD}"
    ]
```

Django starts after MySQL becomes healthy:

```yaml
depends_on:
  mysql:
    condition: service_healthy
```

### Django service

```yaml
django:
  build:
    context: .
    dockerfile: app/Dockerfile
```

The repository root is the build context, while `app/Dockerfile` contains the
image instructions.

The application receives runtime variables from `app/.env`:

```yaml
env_file:
  - ./app/.env
```

Port `8000` is available to other containers but is not published directly to
the host:

```yaml
expose:
  - "8000"
```

The startup command performs these steps:

```yaml
python manage.py migrate &&
python manage.py collectstatic --noinput &&
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```

1. Apply database migrations.
2. Collect static files.
3. Start Gunicorn.

Collected static files are shared with Nginx through the `static_data` volume:

```yaml
volumes:
  - static_data:/app/staticfiles
```

### Nginx service

```yaml
nginx:
  image: nginx:1.27-alpine
```

Nginx is the public reverse proxy. The host port is configurable:

```yaml
ports:
  - "${NGINX_PORT:-8081}:80"
```

The default URL is:

```text
http://localhost:8081
```

To use another host port, set `NGINX_PORT` in `app/.env`, for example:

```env
NGINX_PORT=8082
```

Nginx reads its configuration from the host in read-only mode:

```yaml
- ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
```

### Docker network

All services use the private `django-network` bridge network:

```yaml
networks:
  django-network:
    driver: bridge
```

Docker provides service-name DNS inside this network:

- Django: `http://django:8000`
- MySQL: `mysql:3306`

### Docker volumes

```yaml
volumes:
  mysql_data:
  static_data:
```

- `mysql_data`: persistent MySQL database files.
- `static_data`: collected Django static files served by Nginx.

## `app/Dockerfile`

[app/Dockerfile](app/Dockerfile) defines the Django image.

### Base image

```dockerfile
FROM python:3.12-slim
```

The slim image reduces the base image size compared with the full Python image.

### Runtime environment

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
```

- Prevents Python bytecode files.
- Sends Python logs directly to Docker logs.
- Disables unnecessary pip version checks.
- Prevents pip cache files from increasing the image size.

### Non-root execution

The image creates a dedicated `django` user:

```dockerfile
RUN addgroup --system django \
    && adduser --system --ingroup django django
```

Application files are owned by that user, and the container runs as that user:

```dockerfile
COPY --chown=django:django app/ .
USER django
```

Running as a non-root user reduces the impact of a compromised application.

### Dependency caching

Dependencies are copied and installed before application source code:

```dockerfile
COPY app/requirements.txt /tmp/requirements.txt

RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
```

This allows Docker to reuse the dependency layer when only application code
changes.

### Gunicorn

```dockerfile
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
```

Gunicorn serves the Django WSGI application on the internal port `8000`.

## `nginx/default.conf`

[nginx/default.conf](nginx/default.conf) configures the reverse proxy.

### Listener

```nginx
server {
    listen 80;
    server_name localhost;
}
```

Nginx listens on port `80` inside its container. Compose maps the host port
`8081` to this internal port.

### Static files

```nginx
location /static/ {
    alias /app/staticfiles/;
}
```

Nginx serves requests under `/static/` directly from the shared static volume.
This avoids sending static files through Django.

### Dynamic requests

```nginx
location / {
    proxy_pass http://django:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

All other requests are forwarded to Django. The headers preserve the original
host, client IP, proxy chain, and protocol.

## `app/.env`

[app/.env](app/.env) contains local runtime configuration. It is ignored by
Git and must not be committed because it contains secrets.

### Django settings

```env
DEBUG=True
SECRET_KEY=...
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8082,http://127.0.0.1:8082
```

- `DEBUG=True` is for local development. Use `DEBUG=False` in production.
- `SECRET_KEY` signs sessions, CSRF tokens, and other security-sensitive data.
- `ALLOWED_HOSTS` limits accepted hostnames.
- `CSRF_TRUSTED_ORIGINS` lists browser origins allowed to submit unsafe requests.

The current `.env` lists port `8082`, while Compose defaults to `8081`. These
values must match. Either set `NGINX_PORT=8082`, or change the trusted origins
to:

```env
CSRF_TRUSTED_ORIGINS=http://localhost:8081,http://127.0.0.1:8081
```

### Database settings

The current `.env` contains:

```env
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=taskdb
DB_USER=taskuser
DB_PASSWORD=taskpassword
DB_HOST=mysql
DB_PORT=3306
```

Because `DB_ENGINE` is SQLite, Django currently uses SQLite rather than the
MySQL container. The MySQL service is running, but Django does not connect to
it with this configuration. The MySQL-related values are ignored by SQLite.

To use MySQL, change the engine to:

```env
DB_ENGINE=django.db.backends.mysql
DB_NAME=taskdb
DB_USER=taskuser
DB_PASSWORD=taskpassword
DB_HOST=mysql
DB_PORT=3306
```

The image would also need a MySQL Python driver and its required system
packages, such as `mysqlclient` and the MySQL development libraries. The
current optimized image intentionally does not install those packages because
the current application uses SQLite.

If SQLite remains enabled, its database file should be placed on a persistent
volume if data must survive Django container recreation.

## `.gitignore`

[.gitignore](.gitignore) prevents local-only and generated files from being
committed:

```gitignore
.env
.venv/
__pycache__/
*.pyc
staticfiles/
mysql_data/
.DS_Store
```

This protects environment secrets, virtual environments, Python cache files,
generated static files, local database storage, and macOS metadata.

## Running the application

Run from the repository root:

```bash
docker compose --env-file app/.env up --build
```

Run in the background:

```bash
docker compose --env-file app/.env up --build -d
```

View logs:

```bash
docker compose logs -f
```

Check service status:

```bash
docker compose --env-file app/.env ps
```

Validate the fully resolved Compose configuration:

```bash
docker compose --env-file app/.env config
```

Stop the containers:

```bash
docker compose down
```

Stop the containers and delete named volumes:

```bash
docker compose down -v
```

Be careful with `down -v`: it deletes the MySQL volume and its data.

The application is available at:

```text
http://localhost:8081
```
# django-docker-production
