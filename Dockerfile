FROM python:3.11-slim

WORKDIR /app

# Install zabbix-sender and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    zabbix-sender \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY collector/ collector/
COPY bin/ bin/
COPY config/ config/

RUN pip install --no-cache-dir .

CMD ["python", "-m", "collector", "--config", "config/services.example.yaml", "--flaresolverr-url", "http://flaresolverr:8191/v1", "--zabbix-server", "zabbix-server"]
