# Stage 1: build the React map UI
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN mkdir -p /backend/static && node build.mjs && cp -r ../backend/static /static

# Stage 2: Flask API serving the built UI
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=ui /static ./static
RUN useradd -m rasad
USER rasad
EXPOSE 8000
CMD ["gunicorn", "-w", "2", "--threads", "4", "--timeout", "120", "-b", "0.0.0.0:8000", "app:app"]
