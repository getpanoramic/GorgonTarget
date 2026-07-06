# --- Build / Dependency Stage ---
FROM python:3.11-slim AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Final Lean Runtime Stage ---
FROM python:3.11-alpine

WORKDIR /app

# Copy the pre-installed dependencies from the builder stage
COPY --from=builder /opt/venv /opt/venv
COPY main.py .

# Set system variables for optimal Python container execution
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Run as a non-privileged user for enhanced security
RUN adduser -D appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
