FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if required
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Ensure data directories exist
RUN mkdir -p data/reports config data/parquet

# Default command runs the live scanner in monitoring loop
# You can override this in docker-compose or run command
CMD ["python", "scripts/live_scanner.py", "--mode", "stocks"]
