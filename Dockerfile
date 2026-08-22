# Use a lightweight python image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory in container
WORKDIR /app

# Copy requirements file first to leverage docker cache
COPY msg_router/requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt pytest httpx

# Copy the entire workspace into the container
COPY . .

# Expose port 8000 for FastAPI
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Command to run uvicorn server
CMD ["python", "-m", "uvicorn", "msg_router.server:app", "--host", "0.0.0.0", "--port", "8000"]
