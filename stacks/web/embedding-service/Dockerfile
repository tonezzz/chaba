FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service from host scripts directory
COPY ../../scripts/embeddings/embedding-service.py .

# Expose port
EXPOSE 5000

# Run service
CMD ["python", "embedding-service.py"]
