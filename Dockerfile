FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
COPY web ./web
COPY docs/evidence/native-ai/ai-evaluation.json docs/evidence/native-ai/salesforce-acceptance.json ./docs/evidence/native-ai/
COPY docs/evidence/salesforce-standard/acceptance.json ./docs/evidence/salesforce-standard/
COPY docs/evidence/connected/preview.json docs/evidence/connected/acceptance.json ./docs/evidence/connected/
COPY docs/evidence/research/evaluation.json docs/evidence/research/public-jobs.json docs/evidence/research/reviewer-assessment.json ./docs/evidence/research/
RUN pip install --no-cache-dir --no-deps --no-build-isolation -e . && useradd --user-group --uid 10001 --create-home gtmrunner && mkdir .local && chown gtmrunner .local
USER gtmrunner
EXPOSE 8560
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8560/',timeout=3)"
CMD ["gtm","serve","--container-bind","--workspace",".local/demo"]
