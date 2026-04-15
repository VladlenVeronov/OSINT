FROM python:3.11-slim

WORKDIR /app

# Install cron
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY *.py ./
COPY osint_agent_prompt.md ./
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Persistent data directory: dedup.db + agent.log
# Mount as volume in Coolify: /data
RUN mkdir -p /data

# Cron: every 15 minutes
RUN echo "*/15 * * * * cd /app && /usr/local/bin/python3 agent.py >> /data/agent.log 2>&1" \
    > /etc/cron.d/osint-agent \
    && chmod 0644 /etc/cron.d/osint-agent \
    && crontab /etc/cron.d/osint-agent

ENTRYPOINT ["/docker-entrypoint.sh"]
