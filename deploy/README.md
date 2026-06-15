# Docker Compose notes

## Docker Hub timeout

If `docker compose up --build` fails while resolving images from Docker Hub, for example:

```text
failed to fetch oauth token: Post "https://auth.docker.io/token": i/o timeout
failed to resolve reference "docker.io/..."
```

the compose file and Dockerfiles are usually fine. Docker cannot reach Docker Hub or its auth service from the current network.

This project keeps Docker Hub as the default source, but lets you override image sources through an env file:

```powershell
Copy-Item deploy\.env.example deploy\.env
```

Edit `deploy\.env` and set a registry mirror or private registry that works in your network. Example shape:

```dotenv
DOCKERHUB_LIBRARY_PREFIX=m.daocloud.io/docker.io/library/
PGVECTOR_IMAGE=m.daocloud.io/docker.io/pgvector/pgvector:pg17
REDIS_IMAGE=m.daocloud.io/docker.io/library/redis:7-alpine
RABBITMQ_IMAGE=m.daocloud.io/docker.io/library/rabbitmq:3-management
PROMETHEUS_IMAGE=m.daocloud.io/docker.io/prom/prometheus:v2.55.0
GRAFANA_IMAGE=m.daocloud.io/docker.io/grafana/grafana:11.3.0
```

Then start compose with the env file explicitly:

```powershell
docker compose --env-file deploy\.env -f deploy\docker-compose.yml up --build
```

If you configure a Docker daemon registry mirror instead, no project env file is needed.
