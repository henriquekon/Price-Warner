FROM node:22-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY data ./data
COPY engine ./engine
COPY addons ./addons
COPY main.py ./main.py
COPY --from=frontend-build /frontend/dist ./frontend/dist
EXPOSE 9873
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9873"]
