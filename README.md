# Sonarr to PyMedusa API Proxy

A lightweight, asynchronous FastAPI translation layer designed to proxy Sonarr v3 API calls onto a PyMedusa backend. Perfect for connecting Arr-ecosystem tools to Medusa.

## Quick Start via Docker Compose

```yaml
version: '3.8'

services:
  sonarr-medusa-proxy:
    image: ghcr.io/yourusername/sonarr-medusa-proxy:latest # Or build locally
    build: .
    container_name: sonarr-medusa-proxy
    ports:
      - "8000:8000"
    environment:
      - MEDUSA_URL=http://your-medusa-ip:8081
      - MEDUSA_API_KEY=your_actual_medusa_api_key
      - PROXY_API_KEY=generate_a_secret_token_here
    restart: unless-stopped
