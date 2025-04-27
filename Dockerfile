# Use official slim Python image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y gcc

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Environment variables are loaded manually inside Python from /secrets/env-file
ENV PYTHONUNBUFFERED=1

# Expose the port that Gunicorn will use
EXPOSE 8080

# Start Gunicorn server with 2 workers
CMD ["gunicorn", "--workers=2", "--bind=0.0.0.0:8080", "app:server"]
