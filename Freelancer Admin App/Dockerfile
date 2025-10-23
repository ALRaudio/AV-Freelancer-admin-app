FROM python:3.11-bookworm
ENV PIP_NO_CACHE_DIR=1 PIP_DEFAULT_TIMEOUT=120
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && update-ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel && pip install --retries 10 --timeout 120 -i https://pypi.org/simple -r requirements.txt
COPY . .
ENV FLASK_ENV=production
EXPOSE 8080
CMD ["gunicorn","-b","0.0.0.0:8080","app:app"]
