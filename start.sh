#!/bin/bash
set -e

echo "=== Running migrations ==="
python manage.py migrate --noinput --verbosity 1

echo "=== Collecting static files ==="
python manage.py collectstatic --noinput
echo "=== Static files collected to: ==="
ls -la /app/staticfiles/ 2>/dev/null || echo "WARNING: /app/staticfiles/ not found"

echo "=== Ensuring superuser ==="
python manage.py ensure_superuser

echo "=== Starting gunicorn ==="
exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3 --timeout 120
