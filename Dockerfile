FROM python:3.10-slim

# System deps for psycopg3 + cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc \
      libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Fast dependency install via uv
RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache -e .

COPY kil/ kil/
COPY gunicorn.conf.py .

# Non-root runtime user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

ENV KIL_ENV=PROD \
    FLASK_APP=kil.backend.legacy.app

EXPOSE 5002

CMD ["gunicorn", "-c", "gunicorn.conf.py", "kil.backend.legacy.app:app"]
