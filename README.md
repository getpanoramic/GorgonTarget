# GorgonTarget 🐍🎯

A lightweight, asynchronous translation proxy that acts as a bridge between the **Sonarr v3 API** and a **PyMedusa** backend. 

`GorgonTarget` intercepts API calls from modern ecosystem tools (like request managers, dashboard widgets, or subtitle downloaders) that natively expect a Sonarr instance, translates the data schema, and routes them seamlessly into PyMedusa's modern v2 REST API.

---

## 🚀 Features

* **Ultra-Lightweight & Fast:** Built entirely on Python **FastAPI** and **Uvicorn** using non-blocking asynchronous networking via `httpx`.
* **Smart Schema Translation:** Transparently maps foundational data structures (Series search, lookups, calendars, and episode info) between both ecosystems.
* **Robust Client Support:** Emulates system states, profiles, and storage configurations so modern applications remain fully functional.
* **Production-Ready Docker Build:** Optimized for containerized deployments.

---

## 🛠️ API Support Status

GorgonTarget implements the necessary subset of the Sonarr v3 API to enable core functionality in popular client applications. Endpoints marked as "Not Implemented" are stubs or planned for future development.

| Category | Endpoint | Status |
| :--- | :--- | :--- |
| **Core Media** | `/api/v3/series` | Implemented |
| | `/api/v3/series/{id}` | Implemented |
| | `/api/v3/series/lookup` | Implemented |
| | `/api/v3/series/editor` | Implemented |
| | `/api/v3/rootfolder` | Implemented |
| **Episodes/Files**| `/api/v3/episode` | Implemented |
| | `/api/v3/episode/{id}` | Implemented |
| | `/api/v3/episode/monitor` | Implemented |
| | `/api/v3/episodefile` | Implemented |
| | `/api/v3/episodefile/{id}` | Not Implemented |
| | `/api/v3/episodefile/bulk`| Not Implemented |
| **Activity** | `/api/v3/queue` | Implemented |
| | `/api/v3/queue/{id}` | Implemented |
| | `/api/v3/queue/grabbed` | Not Implemented |
| | `/api/v3/history` | Implemented |
| | `/api/v3/history/series` | Implemented |
| | `/api/v3/history/failed/{id}`| Implemented |
| | `/api/v3/blocklist` | Implemented |
| | `/api/v3/blocklist/{id}` | Implemented |
| **Commands** | `/api/v3/command` | Implemented |
| | `/api/v3/command/{id}` | Implemented |
| **System** | `/api/v3/system/status` | Implemented |
| | `/api/v3/health` | Implemented |
| | `/api/v3/diskspace` | Implemented |
| | `/api/v3/log` | Implemented |
| | `/api/v3/log/file` | Implemented |
| | `/api/v3/system/backup` | Implemented |
| **Configuration** | `/api/v3/qualityprofile` | Implemented |
| | `/api/v3/languageprofile` | Implemented |
| | `/api/v3/delayprofile` | Implemented |
| | `/api/v3/tag` | Implemented |
| | `/api/v3/naming` | Implemented |
| **Integrations**| `/api/v3/indexer` | Implemented |
| | `/api/v3/downloadclient` | Implemented |
| | `/api/v3/importlist` | Implemented |
| | `/api/v3/notification` | Implemented |
| | `/api/v3/remotepathmapping`| Implemented |

---

## 🐳 Quick Start with Docker Compose

Add the following service block to your deployment file:

```yaml
version: '3.8'

services:
  gorgontarget:
    image: ghcr.io/getpanoramic/gorgontarget:latest
    container_name: gorgontarget
    ports:
      - "8888:8888"
    environment:
      - MEDUSA_URL=http://your-medusa-ip:8081
      - MEDUSA_API_KEY=your_actual_medusa_api_key
      - PROXY_API_KEY=generate_a_secure_proxy_token_here
    restart: unless-stopped
```
