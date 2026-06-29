#!/bin/bash

# Start Celery worker in the background
echo "Starting Celery worker..."
celery -A config worker --loglevel=info --concurrency=1 &

# Start Celery beat in the background
echo "Starting Celery beat..."
celery -A config beat --loglevel=info &

# Start Gunicorn server in the foreground
echo "Starting Gunicorn..."
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 2
