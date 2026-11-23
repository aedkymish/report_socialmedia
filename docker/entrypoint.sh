#!/bin/sh
set -e
DATA_DIR="$(dirname "$DJANGO_DB_PATH")"
mkdir -p "$DATA_DIR"

# One-time move from the old Docker volume (mounted read-only at /app/legacy_data)
# into the local ./data folder: only when ./data has no database yet.
if [ -d /app/legacy_data ] && [ -f /app/legacy_data/db.sqlite3 ] && [ ! -f "$DJANGO_DB_PATH" ]; then
  echo "Copying existing data from the old Docker volume into ./data ..."
  cp -a /app/legacy_data/. "$DATA_DIR"/
  echo "Done: $(find "$DATA_DIR" -type f | wc -l) files copied. The old volume is kept as a backup."
fi

mkdir -p "$DJANGO_MEDIA_ROOT"
# Platforms (TikTok especially) change often; a fresh yt-dlp fixes most breakages.
if [ "${YTDLP_AUTO_UPDATE:-1}" = "1" ]; then
  pip install --no-cache-dir -q -U "yt-dlp[default,curl-cffi]" >/dev/null 2>&1 \
    && echo "yt-dlp $(yt-dlp --version)" || echo "yt-dlp update skipped (offline?)"
fi

python manage.py migrate --noinput

# Create the first admin once, if credentials are provided (username = code).
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  python manage.py shell -c "
import os
from accounts.models import User
code = os.environ['DJANGO_SUPERUSER_USERNAME']
if not User.objects.filter(username=code).exists():
    User.objects.create_superuser(code, '', os.environ['DJANGO_SUPERUSER_PASSWORD'],
                                  role=User.Role.APPROVER, full_name='مدير النظام')
    print('Created superuser', code)
"
fi

# Pick up links left pending by a previous restart.
python manage.py collect_evidence >/dev/null 2>&1 &

exec "$@"
