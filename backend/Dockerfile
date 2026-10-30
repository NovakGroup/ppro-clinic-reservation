# Build kontext je kořen repozitáře (kvůli složce frontend/)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ /app/
COPY frontend/ /app/frontend/
# Odstraní případné windowsové konce řádků (CRLF), jinak skript v Linuxu nejde spustit
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

EXPOSE 8000
CMD ["/app/entrypoint.sh"]
