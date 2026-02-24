FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r services/agent_swarm/requirements.txt
CMD ["uvicorn", "services.agent_swarm.app:app", "--host", "0.0.0.0", "--port", "8080"]
