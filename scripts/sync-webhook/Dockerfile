FROM mcr.microsoft.com/playwright/python:v1.49.0-noble
# Playwright base image = Ubuntu 24.04, Python 3.12, Chromium + browser deps.
# The price refresh (/fetch-price) needs a REAL browser: direct HTTP fetching
# is blocked by Cloudflare (403) on Jumia, so curl/urllib can never read a price.
# NOTE: the -jammy variant ships Python 3.10 (NOT 3.12) — it broke the sync
# with f-string SyntaxErrors and must not be used. Noble = 3.12.
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*
# Explicit install: the base image already bundles playwright, but if the
# build ever runs against a base without it, this line (not a silent runtime
# error) is what saves the deploy. playwright-stealth patches the
# automation fingerprints (webdriver flag, plugins, languages...) so the
# store's bot detection sees a normal desktop browser.
RUN python3 -m pip install --no-cache-dir pillow playwright==1.49.0 playwright-stealth
# Build-time smoke test: fail the image build LOUDLY if Playwright cannot be
# imported, instead of deploying an app that answers every price request with
# "Playwright is not installed" (what happened on 2026-11-25).
RUN python3 -c "from playwright.sync_api import sync_playwright; import playwright_stealth; print('playwright + stealth import ok')"
WORKDIR /app
COPY server.py /app/server.py
RUN mkdir -p /data/repo
EXPOSE 8000
CMD ["python3", "/app/server.py"]
