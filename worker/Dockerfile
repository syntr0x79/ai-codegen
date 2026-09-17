FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git openssh-client curl libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# kubectl + helm for devops agents
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && chmod +x kubectl && mv kubectl /usr/local/bin/
RUN curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code

RUN useradd -m -s /bin/bash codegen \
    && git config --system user.name "Factory of Code" \
    && git config --system user.email "factory@localhost"
RUN mkdir -p /home/codegen/.ssh && chown -R codegen:codegen /home/codegen/.ssh

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ssh_config /home/codegen/.ssh/config
RUN chmod 600 /home/codegen/.ssh/config && chown codegen:codegen /home/codegen/.ssh/config

COPY src/ src/
COPY worker/ worker/
COPY agents.yaml .

RUN mkdir -p /app/data /tmp/factory-worker && chown -R codegen:codegen /app /tmp/factory-worker

USER codegen
CMD ["python", "-m", "worker.src.main"]
