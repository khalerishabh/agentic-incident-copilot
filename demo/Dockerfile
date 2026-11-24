FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir --retries 10 --timeout 60 fastapi "uvicorn[standard]" httpx prometheus-client
COPY demo ./demo
EXPOSE 8000
CMD ["uvicorn", "demo.main:app", "--host", "0.0.0.0", "--port", "8000"]
