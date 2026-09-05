#!/bin/bash

# Run database migrations
echo "Running database migrations..."
python manage.py migrate --noinput

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
echo "Starting Gunicorn..."
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 2
