FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY alembic.ini entrypoint.sh ./
COPY migrations ./migrations
RUN useradd -m appuser && chown -R appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/ready')" || exit 1
# One worker on purpose: the login-lockout counter lives in process memory. Scale with a shared store first.
CMD ["./entrypoint.sh"]
