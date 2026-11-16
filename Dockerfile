FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then \
        npm ci --no-audit --no-fund; \
    else \
        npm install --no-audit --no-fund; \
    fi
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
RUN npm run build

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp

WORKDIR /app
COPY requirements.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps firefox \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*
COPY data ./data
COPY engine ./engine
COPY addons ./addons
COPY main.py ./main.py
COPY --from=frontend-builder /frontend/dist ./frontend/dist

EXPOSE 9873
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9873"]
