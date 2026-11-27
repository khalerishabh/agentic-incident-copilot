# One image for the copilot API and every MCP server; the command picks which one runs.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY demo ./demo
RUN pip install --retries 10 --timeout 60 .

COPY copilot.yaml ./
COPY runbooks ./runbooks

RUN useradd --system --uid 10001 --no-create-home copilot
USER copilot

CMD ["uvicorn", "copilot.api:app", "--host", "0.0.0.0", "--port", "8080"]
