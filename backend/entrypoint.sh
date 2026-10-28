
#!/bin/sh
set -e

echo "Running database migrations..."
python -m alembic upgrade head

echo "Starting application..."
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips="*"
