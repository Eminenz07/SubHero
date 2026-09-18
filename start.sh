#!/bin/bash

PORT="${PORT:-8000}"

# Run database migrations
echo "Running database migrations..."
python manage.py migrate --noinput || echo "Warning: Migration failed or timed out, continuing..."

# Start Celery worker and beat only if REDIS_URL is configured
if [ -n "$REDIS_URL" ]; then
    echo "Starting Celery worker..."
    celery -A config worker --loglevel=info --concurrency=1 &

    echo "Starting Celery beat..."
    celery -A config beat --loglevel=info &
else
    echo "REDIS_URL is not set. Running Celery in eager mode without background workers."
fi

# Start Gunicorn server in the foreground
echo "Starting Gunicorn on port ${PORT}..."
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT}" --workers 2 --threads 2
