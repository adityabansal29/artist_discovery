# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Claude Code is invoked by the research runner for Web/X and synthesis.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates nodejs npm \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/outputs /app/hashtags \
    && chown -R app:app /app
USER app
ENV HOME=/home/app
ENV HOST=0.0.0.0
ENV PORT=8780
ENV PYTHONUNBUFFERED=1
EXPOSE 8780

CMD ["python", "dashboard_server.py"]
