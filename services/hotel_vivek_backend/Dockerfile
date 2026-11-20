# Hotel Vivek API image = hrms-core backend + this client's YAML and its hotel_vivek package.
# Build context is the services/ folder:  docker build -f hotel_vivek_backend/Dockerfile services
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    CLIENT_CONFIG=/app/client/client.yaml CLIENT_PACKAGE_PATH=/app/client
WORKDIR /app

COPY hrms-core/backend/requirements.txt .
RUN pip install -r requirements.txt

COPY hrms-core/backend/ /app/
COPY hotel_vivek_backend/client.yaml /app/client/client.yaml
COPY hotel_vivek_backend/hotel_vivek/ /app/client/hotel_vivek/
RUN sed -i "s/\r$//" docker-entrypoint.sh && chmod +x docker-entrypoint.sh && useradd -m hrms && mkdir -p /app/storage && chown -R hrms /app
USER hrms

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')"
ENTRYPOINT ["./docker-entrypoint.sh"]
