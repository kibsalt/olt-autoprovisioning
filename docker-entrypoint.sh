#!/bin/sh
set -e

echo "[entrypoint] Waiting for MariaDB..."
until python3 -c "
import pymysql, os, sys
try:
    pymysql.connect(
        host=os.environ.get('OLT_DB_HOST','127.0.0.1'),
        port=int(os.environ.get('OLT_DB_PORT',3306)),
        user=os.environ.get('OLT_DB_USER','olt_api'),
        password=os.environ.get('OLT_DB_PASSWORD','changeme'),
        database=os.environ.get('OLT_DB_NAME','olt_provisioning'),
        connect_timeout=3,
    ).close()
    sys.exit(0)
except Exception as e:
    sys.exit(1)
" 2>/dev/null; do
  echo "[entrypoint] DB not ready, retrying in 3s..."
  sleep 3
done

echo "[entrypoint] Running database migrations..."
alembic upgrade head || {
  echo "[entrypoint] Alembic failed — creating tables directly..."
  python3 -c "
from sqlalchemy import create_engine
from app.config import settings
import app.models
from app.models.base import Base
engine = create_engine(settings.sync_database_url)
Base.metadata.create_all(engine)
print('[entrypoint] Tables created.')
engine.dispose()
"
}

echo "[entrypoint] Starting OLT Provisioning API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
