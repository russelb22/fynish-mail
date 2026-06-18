FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY .env.example /app/.env.example

RUN mkdir -p /app/data /app/tmp

ENV FYNISH_APP_ENV=cloud
ENV FYNISH_DATA_DIR=/app/data
ENV FYNISH_SQLITE_DATABASE_PATH=/app/data/fynish.sqlite3
ENV FYNISH_GOOGLE_TOKEN_DIR=/app/data/google_tokens
ENV FYNISH_GOOGLE_CLIENT_SECRETS_PATH=/app/secrets/google-credentials.json
ENV FYNISH_FRONTEND_URL=https://fynish-frontend.example.com/
ENV FYNISH_BACKEND_CORS_ORIGINS=https://fynish-frontend.example.com
ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
