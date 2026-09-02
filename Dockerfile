FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server
COPY api ./api
COPY railway_app.py ./
COPY data/all-in-grok.sqlite3.gz ./data/all-in-grok.sqlite3.gz

EXPOSE 8080

CMD ["sh", "-c", "uvicorn railway_app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
