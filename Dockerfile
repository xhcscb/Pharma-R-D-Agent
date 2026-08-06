FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN python -m pip install --upgrade pip uv==0.12.2 \
    && uv export --locked --no-dev \
       --extra documents --extra audio --extra ml \
       --no-emit-project --format requirements-txt \
       --output-file /tmp/requirements.txt \
    && python -m pip install --require-hashes -r /tmp/requirements.txt

COPY src ./src
RUN python -m pip install --no-deps .

COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY config ./config
COPY schemas ./schemas

CMD ["uvicorn", "pharma_data.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
