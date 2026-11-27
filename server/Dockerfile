# Build from the folder that holds server/ and workflows/ side by side:
#   docker build -f server/Dockerfile -t resolve-server .
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/server
COPY workflows /srv/workflows
COPY server/pyproject.toml ./
COPY server/app ./app
COPY server/config ./config
COPY server/data ./data
COPY server/alembic.ini ./alembic.ini

RUN pip install --no-cache-dir /srv/workflows . \
    && mkdir -p data/tessdata data/objects \
    && cp /usr/share/tesseract-ocr/*/tessdata/eng.traineddata /usr/share/tesseract-ocr/*/tessdata/hin.traineddata data/tessdata/

ENV APP_ENV=prod
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"]
