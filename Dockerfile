FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock && useradd --uid 10001 --create-home radar
COPY mochex_radar ./mochex_radar
COPY cluster_radar ./cluster_radar
# Release worktrees are created with a private umask. Normalize application
# readability and create the read-only research mountpoint before switching user.
RUN mkdir -p /research && chmod -R a+rX /app /research
USER radar
CMD ["uvicorn", "mochex_radar.api:app", "--host", "0.0.0.0", "--port", "8000"]
