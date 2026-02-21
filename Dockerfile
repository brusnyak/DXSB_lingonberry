# Use official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create directory for reports and data
RUN mkdir -p data/reports data/parquet

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Default command: Run the crypto scanner (can be overridden)
CMD ["python", "scripts/live_scanner.py", "--mode", "crypto", "--limit", "20"]
