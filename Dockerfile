FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline/ ./pipeline/
COPY prompts/ ./prompts/
COPY specs/ ./specs/

ENV PYTHONUNBUFFERED=1
ENV GIT_PYTHON_REFRESH=quiet

CMD ["tail", "-f", "/dev/null"]