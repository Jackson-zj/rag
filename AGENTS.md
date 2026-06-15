# Agent Notes

## Project Overview

This repository is an Enterprise RAG MVP with three local services:

- `frontend`: React + TypeScript + Vite admin UI.
- `backend-java`: Spring Boot business API, auth demo, sessions, document metadata, and SSE aggregation.
- `ai-service`: FastAPI RAG service, in-memory chunk index, deterministic embedding fallback, LangGraph-style orchestration, and OpenAI-compatible model calls when configured.

Current implementation is demo/in-memory first. Uploaded documents, vector chunks, sessions, user tokens, and chat memory are not persisted to a database. Restarting Java or AI services clears their in-memory state.

## Recommended Local Environments

Use one isolated environment per runtime, not one environment per framework.

### AI Service

Recommended Python version: `3.12`.

Recommended conda environment name: `rag-ai`.

Create and install:

```powershell
conda create -n rag-ai python=3.12 -y
conda activate rag-ai
cd D:\pythonWorkspace\RAG\ai-service
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Do not use the shared `base` conda environment or the old `torch311` environment for this project. Previous startup failures were caused by incompatible `fastapi` and `starlette` versions in a reused environment.

Current key Python dependencies are pinned in `ai-service/requirements.txt`, including:

- `fastapi==0.124.0`
- `starlette==0.50.0`
- `uvicorn[standard]==0.38.0`
- `pydantic==2.12.5`
- `httpx==0.28.1`
- `langgraph==1.1.6`

AI model defaults:

- `MODEL_BASE_URL`: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- `MODEL_NAME`: `qwen3.7-plus`
- API key lookup order: `MODEL_API_KEY` first, then `DASHSCOPE_API_KEY`

Set the key in the shell before starting `ai-service`:

```powershell
$env:DASHSCOPE_API_KEY='your-key'
```

### Frontend

Use Node/npm, not conda.

```powershell
cd D:\pythonWorkspace\RAG\frontend
npm install
npm run dev
```

### Java Backend

Use JDK 17 and the checked-in Maven wrapper.

```powershell
cd D:\pythonWorkspace\RAG
$env:JAVA_HOME='C:\Program Files\Java\jdk-17.0.3.1'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\mvnw.cmd test
```

## Start Commands

Start AI service:

```powershell
conda activate rag-ai
cd D:\pythonWorkspace\RAG\ai-service
$env:DASHSCOPE_API_KEY='your-key'
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Start Java backend:

```powershell
cd D:\pythonWorkspace\RAG\backend-java
..\mvnw.cmd spring-boot:run
```

Start frontend:

```powershell
cd D:\pythonWorkspace\RAG\frontend
npm run dev
```

Start all services with Docker Compose from WSL/Linux:

```bash
cd /mnt/d/pythonWorkspace/RAG
cp deploy/.env.example deploy/.env
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up --build
```

Use foreground Compose startup while debugging so image pull, build, and service logs are visible. After startup is known-good, use detached mode:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs -f
```

Stop Docker Compose services:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml down
```

If Docker Hub is unreachable, edit `deploy/.env` and set `DOCKERHUB_LIBRARY_PREFIX`, `PGVECTOR_IMAGE`, `REDIS_IMAGE`, `RABBITMQ_IMAGE`, `PROMETHEUS_IMAGE`, and `GRAFANA_IMAGE` to a reachable registry mirror. If a host port is occupied, change the corresponding port variable, for example `BACKEND_PORT=18080` maps host port `18080` to container port `8080`.

Expected local URLs:

- Frontend: `http://localhost:5173`
- Java backend: `http://localhost:8080`
- AI service docs: `http://localhost:8000/docs`
- RabbitMQ console: `http://localhost:15672`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

## Validation Commands

AI service tests:

```powershell
conda activate rag-ai
cd D:\pythonWorkspace\RAG\ai-service
python -m unittest discover -s tests
```

Frontend build:

```powershell
cd D:\pythonWorkspace\RAG\frontend
npm run build
```

Java tests:

```powershell
cd D:\pythonWorkspace\RAG
$env:JAVA_HOME='C:\Program Files\Java\jdk-17.0.3.1'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\mvnw.cmd test
```

## Demo Accounts

- `admin / admin123`: access to HR and Tech Architecture knowledge bases.
- `analyst / analyst123`: access to HR knowledge base only.

Auth is demo-only. Tokens are UUIDs stored in Java memory and are lost on backend restart.

## Common Gotchas

- If the browser shows retrieval/citations but no useful answer, check that the AI service on port `8000` is running the latest code.
- Restarting `ai-service` clears uploaded document chunks because `CHUNKS` is an in-memory list.
- Restarting `backend-java` clears sessions, document metadata, tokens, and demo store state.
- If FastAPI fails with `Router.__init__() got an unexpected keyword argument 'on_startup'`, the Python environment has a FastAPI/Starlette version conflict. Recreate `rag-ai` and reinstall `requirements.txt`.
- `backend-java` health may report unhealthy if optional local infrastructure such as RabbitMQ is not available; core demo endpoints can still work.
