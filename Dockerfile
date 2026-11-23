# syntax=docker/dockerfile:1
# Static ffmpeg/ffprobe (amd64 + arm64) — avoids apt-get, which fails behind
# some proxies / Docker Desktop setups ("At least one invalid signature").
FROM mwader/static-ffmpeg:7.1 AS ffmpeg

# Official Playwright image: Python + Chromium + all browser system libraries.
FROM mcr.microsoft.com/playwright/python:v1.65.2-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=0 \
    DJANGO_DB_PATH=/app/data/db.sqlite3 \
    DJANGO_MEDIA_ROOT=/app/data/media

# ffmpeg lets yt-dlp merge separate video/audio streams into one mp4.
COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/

WORKDIR /app
COPY requirements.txt .
# Optional build secret "extra_ca": only for networks with a TLS-intercepting proxy.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir -r requirements.txt

COPY . .
# Strip Windows CRLF line endings (git autocrlf) so the script runs on Linux.
RUN sed -i 's/\r$//' docker/entrypoint.sh \
    && chmod +x docker/entrypoint.sh \
    && DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput

VOLUME ["/app/data"]
EXPOSE 8000
ENTRYPOINT ["sh", "/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "2", "--threads", "4", "--timeout", "120", "--access-logfile", "-"]
