#!/bin/sh
set -e

# Wait for database to be ready
echo "Waiting for database..."
while ! python -c "
import os, sys
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.db import connections
try:
    connections['default'].cursor()
except Exception:
    sys.exit(1)
" 2>/dev/null; do
  echo "  DB not ready, retrying in 2s..."
  sleep 2
done
echo "Database ready!"

# Auto makemigrations in dev mode
if [ "$DEBUG" = "True" ]; then
  echo "DEV: Running makemigrations..."
  python manage.py makemigrations --noinput 2>/dev/null || true
fi

# Always run migrate
echo "Running migrations..."
python manage.py migrate --noinput

# Collect static in prod
if [ "$DEBUG" != "True" ]; then
  echo "Collecting static files..."
  python manage.py collectstatic --noinput 2>/dev/null || true
fi

echo "Starting: $@"
exec "$@"
