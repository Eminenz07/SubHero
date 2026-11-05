# ==========================================
# SubHero — Production Dockerfile
# Multi-stage build for optimal image size
# ==========================================

# Stage 1: Build dependency wheels
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies for C-extensions (like psycopg or argon2-cffi)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/base.txt requirements/production.txt ./
RUN pip install --no-cache-dir --user -r production.txt

# Stage 2: Compile Tailwind CSS from static/css/input.css
# Guarantees static/css/app.css is always rebuilt from source at deploy time,
# so the shipped CSS can never drift from input.css again.
FROM node:20-slim AS css-builder

WORKDIR /app

# Install the exact dependency tree from the committed lock file
COPY package.json package-lock.json ./
RUN npm ci

# Tailwind scans these paths for utility classes (see tailwind.config.js)
COPY tailwind.config.js ./
COPY static/css/input.css ./static/css/input.css
COPY static/js ./static/js
COPY templates ./templates
COPY apps ./apps

RUN npm run build:css

# Stage 3: Clean minimal runtime image
FROM python:3.12-slim

WORKDIR /app

# Install runtime library dependencies (libpq for PostgreSQL connection)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder stage
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application source code
COPY . .

# Create logs directory
RUN mkdir -p logs

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

# Use the freshly compiled CSS instead of the committed build artifact
COPY --from=css-builder /app/static/css/app.css ./static/css/app.css

# Pre-compile static files during build using a dummy SECRET_KEY and DATABASE_URL
RUN SECRET_KEY=build-dummy-key-for-collectstatic DATABASE_URL=sqlite:///:memory: python manage.py collectstatic --noinput

# Copy start script
COPY start.sh .
RUN chmod +x start.sh

# Expose server port
EXPOSE 8000

# Start using script
CMD ["./start.sh"]
