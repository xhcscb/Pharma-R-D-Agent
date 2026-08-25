FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
ARG PHARMA_EXTRAS=""
RUN python -m pip install --upgrade pip uv==0.12.2 \
    && set -eu \
    && extra_args="" \
    && old_ifs="$IFS" \
    && IFS=',' \
    && for extra in $PHARMA_EXTRAS; do \
         case "$extra" in \
           "") ;; \
           documents|audio|ml) extra_args="$extra_args --extra $extra" ;; \
           *) echo "Unsupported PHARMA_EXTRAS value: $extra" >&2; exit 2 ;; \
         esac; \
       done \
    && IFS="$old_ifs" \
    && uv export --locked --no-dev $extra_args \
       --no-emit-project --format requirements-txt \
       --output-file /tmp/requirements.txt \
    && python -m pip install --require-hashes -r /tmp/requirements.txt

COPY README.md ./
COPY src ./src
RUN python -m pip install --no-deps .

COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY config ./config
COPY schemas ./schemas

CMD ["uvicorn", "pharma_data.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
