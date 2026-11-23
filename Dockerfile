FROM python:3.12-slim

# Create a non-root application user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Copy dependency definition first for layer caching
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure reports directory exists with proper permissions
RUN mkdir -p /app/reports && chown -R appuser:appuser /app

USER appuser

# Default command runs main.py (arguments can be overridden)
CMD ["python", "main.py"]
