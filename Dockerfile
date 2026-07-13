# --- Build / Dependency Stage (Switched to Alpine) ---
FROM python:3.11-alpine AS builder

WORKDIR /app

# Alpine requires build-base/gcc to compile certain python wheels if pre-built wheels aren't found
RUN apk add --no-cache build-base

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Final Lean Runtime Stage ---
FROM python:3.11-alpine

WORKDIR /app

# Copy the pre-installed musl-compiled dependencies
COPY --from=builder /opt/venv /opt/venv

# COPY THE ENTIRE PACKAGE INSTEAD OF JUST main.py
COPY gorgontarget/ ./gorgontarget/

# Set system variables for optimal Python container execution
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Run as a non-privileged user for enhanced security
RUN adduser -D appuser
USER appuser

# Standardized to 8888
EXPOSE 8888

# Update the Uvicorn path to point to the package
CMD ["uvicorn", "gorgontarget.main:app", "--host", "0.0.0.0", "--port", "8888", "--workers", "1"]
