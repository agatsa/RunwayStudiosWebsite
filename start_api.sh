#!/bin/bash
export DATABASE_URL="postgresql://postgres:job314@34.93.56.252:5432/wa_agency"
export CRON_TOKEN="dev"
cd /c/Users/rahul/Downloads/wa-agency-bot-extracted/wa-agency-bot
uvicorn services.agent_swarm.app:app --port 8081 --host 127.0.0.1
