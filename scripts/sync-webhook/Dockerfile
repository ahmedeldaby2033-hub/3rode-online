FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy
# Playwright base image = Python 3.12 + Chromium + all browser deps.
# The price refresh (/fetch-price) needs a REAL browser: direct HTTP fetching
# is blocked by Cloudflare (403) on Jumia, so curl/urllib can never read a price.
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pillow
WORKDIR /app
COPY server.py /app/server.py
RUN mkdir -p /data/repo
EXPOSE 8000
CMD ["python3", "/app/server.py"]
