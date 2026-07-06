# GorgonTarget 🐍🎯

A lightweight, asynchronous translation proxy that acts as a bridge between the **Sonarr v3 API** and a **PyMedusa** backend. 

`GorgonTarget` intercepts API calls from modern ecosystem tools (like request managers, dashboard widgets, or subtitle downloaders) that natively expect a Sonarr instance, translates the data schema, and routes them seamlessly into PyMedusa's modern v2 REST API.

---

## 🚀 Features

* **Ultra-Lightweight & Fast:** Built entirely on Python **FastAPI** and **Uvicorn** using non-blocking asynchronous networking via `httpx`. Consumes less than 30MB of RAM.
* **Smart Schema Translation:** Transparently maps foundational data structures (Series search, lookups, calendars, and episode info) between both ecosystems.
* **Robust Client Support:** Emulates system states, profiles, and storage configurations so modern applications remain fully functional without throwing errors.
* **Production-Ready Docker Build:** Built on a secure, multi-stage Alpine Linux base image that runs as a non-root user.

---

## 🛠️ Quick Start with Docker Compose

The easiest way to deploy `GorgonTarget` alongside your existing media stack is via `docker-compose`. 

Add the following service block to your deployment file:

```yaml
version: '3.8'

services:
  gorgontarget:
    image: ghcr.io/getpanoramic/gorgontarget:latest
    container_name: gorgontarget
    ports:
      - "8000:8000"
    environment:
      - MEDUSA_URL=http://your-medusa-ip:8081
      - MEDUSA_API_KEY=your_actual_medusa_api_key
      - PROXY_API_KEY=generate_a_secure_proxy_token_here
    restart: unless-stopped
