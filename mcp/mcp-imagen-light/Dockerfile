FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for image processing
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create output directory for generated images
RUN mkdir -p /app/images

# Expose port
EXPOSE 8020

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8020"]
