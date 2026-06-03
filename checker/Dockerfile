FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject first and create a minimal stub so pip can resolve deps
# without needing the real source. Real source is copied after install so
# the dependency layer is cached independently of code changes.
COPY pyproject.toml .
RUN mkdir -p app && touch app/__init__.py
RUN pip install --no-cache-dir -e ".[dev]"

# Now overlay real source (invalidates this layer on code change, not pip layer)
COPY . .

CMD ["python", "-m", "app.worker"]
