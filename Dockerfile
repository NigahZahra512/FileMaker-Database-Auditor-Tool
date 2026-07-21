# DAY 5: Dockerfile
# --------------------------------------------------------------------
# Packages the whole tool (FastAPI backend + static frontend) into one
# image, so anyone can run it with `docker compose up` and never has
# to install Python, pip packages, or anything else manually.

FROM python:3.12-slim

# Keep Python from writing .pyc files / buffering output -- makes
# container logs show up immediately instead of getting stuck in a
# buffer.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (separate layer) so Docker can reuse
# this layer on rebuilds as long as requirements.txt hasn't changed --
# makes repeated `docker compose up --build` much faster while
# actively developing.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the actual application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
