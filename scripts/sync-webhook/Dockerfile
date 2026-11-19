FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pillow
WORKDIR /app
COPY server.py /app/server.py
RUN mkdir -p /data/repo
EXPOSE 8000
CMD ["python3", "/app/server.py"]
