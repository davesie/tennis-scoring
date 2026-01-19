FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/
COPY static/ ./static/
COPY templates/ ./templates/

# Create data directory for SQLite
RUN mkdir -p /app/data

# Set environment variables
ENV DATABASE_URL=sqlite+aiosqlite:///./data/tennis.db
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
