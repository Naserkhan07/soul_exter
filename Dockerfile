FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY shorts_bot ./shorts_bot
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
CMD ["shorts-bot"]
