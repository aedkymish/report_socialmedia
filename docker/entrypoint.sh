#!/bin/sh
set -e
mkdir -p "$(dirname "$DJANGO_DB_PATH")" "$DJANGO_MEDIA_ROOT"
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
