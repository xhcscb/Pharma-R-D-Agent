FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
ARG APP_EXTRAS=documents,audio,ml
RUN python -m pip install --upgrade pip && python -m pip install ".[${APP_EXTRAS}]"

COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY config ./config
COPY schemas ./schemas

CMD ["uvicorn", "pharma_data.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
