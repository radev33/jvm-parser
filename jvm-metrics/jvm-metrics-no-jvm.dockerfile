# Use lightweight Python image
FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service code
COPY jvm-metrics.py .

# Expose a default port (can be overridden via env)
EXPOSE 9100

# Run with environment variables
CMD ["python", "jvm-metrics.py"]