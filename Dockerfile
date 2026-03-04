FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/app \
    PATH=/home/app/.local/bin:$PATH

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic ./alembic

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && addgroup --system app \
    && adduser --system --ingroup app --home /home/app app \
    && mkdir -p /home/app \
    && chown -R app:app /app /home/app

USER app

EXPOSE 8000

CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8000", "--workers", "2"]