FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY bot_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot service code
COPY bot_service/ bot_service/

# Expose port
EXPOSE 8000

# Run
CMD ["uvicorn", "bot_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
