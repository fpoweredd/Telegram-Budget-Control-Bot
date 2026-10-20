FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DB_PATH=/data/budget.db

WORKDIR /app

RUN useradd --create-home --uid 10001 bot \
    && mkdir -p /data /app/logs \
    && chown bot:bot /data /app/logs

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src

USER bot
VOLUME ["/data", "/app/logs"]

CMD ["python", "-m", "src"]
