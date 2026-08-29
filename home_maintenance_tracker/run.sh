#!/usr/bin/with-contenv bashio
set -e

export HMT_DATA_DIR="/data"
export HMT_MAX_UPLOAD_MB="$(bashio::config 'max_upload_mb')"

cd /app
exec gunicorn \
  --workers 1 \
  --threads 4 \
  --bind 0.0.0.0:8099 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - \
  app:app

