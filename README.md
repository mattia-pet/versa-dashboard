# Versa SE Dashboard

Dark-mode PM dashboard for Versa Networks Sales Engineers.

## Features

- **Task queue** — live from `OPEN-ITEMS.md`, filterable by customer
- **Customer pills** — click any customer to see their tasks + support tickets
- **Freshdesk integration** — live ticket data via Freshdesk REST API, cached 30 min
- **Keyboard shortcuts** — Enter (approve), S (skip), D (delete), ↑↓ (navigate)

## Stack

- Frontend: `task-flow.html` (vanilla JS, dark-mode)
- Backend: Flask on port 8081
- Data source: `OPEN-ITEMS.md` (read live on each request)
- Ticket source: Freshdesk REST API (`versanetworks.freshdesk.com`)

## Setup

```bash
pip install flask flask-cors requests
cd backend && python3 server.py
# open http://localhost:8081
```

### Freshdesk API Key

Place your Freshdesk API key (from Profile Settings → View API Key) in:

```
data/freshdesk.key
```

This file is gitignored — never commit it.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SE_BOT_ROOT` | `../SE-Bot` | Path to SE-Bot repo (for OPEN-ITEMS.md) |
| `OPEN_ITEMS_FILE` | `$SE_BOT_ROOT/OPEN-ITEMS.md` | Override task source directly |
| `FRESHDESK_API_KEY` | _(from data/freshdesk.key)_ | Fallback if key file missing |

## Customers with live tickets

| Customer | Freshdesk Company ID |
|----------|---------------------|
| Backblaze | 23000106178 |
| NM DOH | 23000107078 |

Other customers show tasks only (no Freshdesk company on record).
