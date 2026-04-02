FROM python:3.12-slim

WORKDIR /app

# Install dependencies (separate layer for caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

# Copy application source
COPY . .

# Entrypoint: run DB migration then start API
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
