FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# The app runs as user "app" (uid 1000). It starts as root only so the entrypoint can make the mounted disk writable.
RUN useradd --uid 1000 --create-home app && mkdir -p /data && chown -R app:app /app /data && chmod +x /app/docker-entrypoint.sh
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s CMD python -c "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '8000'), timeout=4)" || exit 1
ENTRYPOINT ["/app/docker-entrypoint.sh"]
# PORT is set by Render (default 10000); 8000 elsewhere. app.seed copies the shipped institutes onto the disk the first time.
CMD ["sh", "-c", "python -m app.seed && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
