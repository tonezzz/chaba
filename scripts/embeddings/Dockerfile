FROM gperdrizet/llms-gpu:latest

WORKDIR /app

# Downgrade NumPy to fix PyTorch compatibility
RUN pip install "numpy<2"

# Install Flask
RUN pip install flask==3.0.0

# Copy GPU service
COPY embedding-service-gpu.py embedding-service.py

# Expose port
EXPOSE 5000

# Run service
CMD ["python", "embedding-service.py"]