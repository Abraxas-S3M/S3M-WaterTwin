# syntax=docker/dockerfile:1

# --- Stage 1: build the React dashboard -----------------------------------
FROM node:22-alpine AS dashboard-build
WORKDIR /build
COPY apps/dashboard/package.json apps/dashboard/package-lock.json* ./
RUN npm install
COPY apps/dashboard/ ./
RUN npm run build

# --- Stage 2: Python API that also serves the built dashboard -------------
FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DASHBOARD_STATIC_DIR=/app/static

COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/api/app ./app
COPY --from=dashboard-build /build/dist ./static

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
