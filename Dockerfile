FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir ".[test]"

COPY . .

CMD ["python", "-m", "app.cli", "--help"]
