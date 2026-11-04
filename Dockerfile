FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY mochex_radar ./mochex_radar
RUN pip install --no-cache-dir . && useradd --create-home radar
USER radar

CMD ["uvicorn", "mochex_radar.api:app", "--host", "0.0.0.0", "--port", "8000"]
