FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the shared agent_swarm package (for connectors + config)
COPY services/agent_swarm /app/services/agent_swarm
COPY services/google_ads_ingestion /app/services/google_ads_ingestion

EXPOSE 8080
CMD ["uvicorn", "services.google_ads_ingestion.app:app", "--host", "0.0.0.0", "--port", "8080"]
