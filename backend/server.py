#!/usr/bin/env python3
"""
SE-Bot Dashboard Server
Flask API that serves monitoring data
"""

from flask import Flask, jsonify, send_file, request
from flask_cors import CORS
import json
import os
import re
import threading
import time
import requests as http_requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
import subprocess

app = Flask(__name__)
CORS(app)  # Enable CORS for local development

# Paths
DASHBOARD_ROOT = Path(__file__).parent.parent
DATA_DIR = DASHBOARD_ROOT / "data"
METRICS_FILE = DATA_DIR / "metrics.json"
STATUS_FILE = DATA_DIR / "status.json"
TASKS_FILE = DASHBOARD_ROOT.parent / "TASKS.md"
OPEN_ITEMS_FILE = DASHBOARD_ROOT.parent / "OPEN-ITEMS.md"
TASK_STATE_FILE = DATA_DIR / "task-state.json"
TWITTER_DRAFTS = DASHBOARD_ROOT.parent / "social" / "content" / "twitter" / "drafts"
TWITTER_SCHEDULED = DASHBOARD_ROOT.parent / "social" / "content" / "twitter" / "scheduled"
TWITTER_POSTED = DASHBOARD_ROOT.parent / "social" / "content" / "twitter" / "posted"


def load_task_state():
    if TASK_STATE_FILE.exists():
        with open(TASK_STATE_FILE) as f:
            return json.load(f)
    return {}


def save_task_state(state):
    DATA_DIR.mkdir(exist_ok=True)
    with open(TASK_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def parse_open_items():
    """Parse OPEN-ITEMS.md into tasks for task-flow.html"""
    if not OPEN_ITEMS_FILE.exists():
        return []

    tasks = []
    current_section = ''
    current_priority = 'medium'
    task_id = 0

    priority_map = {'🔴': 'high', '🟡': 'medium', '🔵': 'low', '📋': 'low'}

    with open(OPEN_ITEMS_FILE) as f:
        for line in f:
            line_s = line.strip()

            if line_s.startswith('## '):
                for emoji, prio in priority_map.items():
                    if emoji in line_s:
                        current_priority = prio
                        break
                current_section = re.sub(r'^##\s*[🔴🟡🔵📋]\s*', '', line_s).strip()
                continue

            if not (line_s.startswith('- [ ]') or line_s.startswith('- [~]')):
                continue

            status = 'in_progress' if '[~]' in line_s else 'pending'
            text = re.sub(r'^- \[[~ ]\]\s*', '', line_s)

            # Extract [CUSTOMER] tag like **[NAF]** Prepare response...
            customer_match = re.match(r'\*\*\[([^\]]+)\]\*\*\s*(.*)', text)
            if customer_match:
                customer = customer_match.group(1)
                task_text = customer_match.group(2)
            else:
                customer = current_section
                task_text = text

            # Extract priority override like **MEDIUM** Fix Telegram...
            prio_override = None
            prio_match = re.match(r'\*\*(HIGH|MEDIUM|LOW)\*\*\s*(.*)', task_text)
            if prio_match:
                prio_override = prio_match.group(1).lower()
                task_text = prio_match.group(2)

            task_id += 1
            tasks.append({
                'id': f'task-{task_id}',
                'title': task_text,
                'description': f'[{customer}]',
                'type': 'follow_up',
                'priority': prio_override or current_priority,
                'status': status,
                'customer': customer,
                'source': current_section,
                'context': task_text,
                'proposed_response': None,
                'from': None,
                'action_items': None,
                'meeting_time': None,
            })

    return tasks


@app.route('/')
def index():
    """Serve the task-flow dashboard"""
    return send_file(DASHBOARD_ROOT / 'task-flow.html')


@app.route('/task-flow.html')
def task_flow():
    return send_file(DASHBOARD_ROOT / 'task-flow.html')


@app.route('/old')
def old_index():
    return send_file(DASHBOARD_ROOT / 'frontend' / 'index.html')


@app.route('/api/status')
def get_status():
    """Get overall system status"""
    try:
        with open(STATUS_FILE, 'r') as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"error": "Status file not found. Run monitor.py first."}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/metrics')
def get_metrics():
    """Get detailed metrics"""
    try:
        with open(METRICS_FILE, 'r') as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"error": "Metrics file not found. Run monitor.py first."}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/refresh')
def refresh_metrics():
    """Trigger a manual metrics refresh"""
    try:
        monitor_script = DASHBOARD_ROOT / "backend" / "monitor.py"
        result = subprocess.run(
            ["python3", str(monitor_script)],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            return jsonify({"status": "success", "message": "Metrics refreshed"})
        else:
            return jsonify({"status": "error", "message": result.stderr}), 500

    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "Refresh timed out"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/logs/<project_id>')
def get_project_logs(project_id):
    """Get recent logs for a specific project"""
    try:
        with open(METRICS_FILE, 'r') as f:
            data = json.load(f)

        if project_id not in data["projects"]:
            return jsonify({"error": "Project not found"}), 404

        logs = data["projects"][project_id].get("recent_logs", [])
        return jsonify({"project_id": project_id, "logs": logs})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def parse_tasks_md(filepath):
    """Parse TASKS.md into structured task data"""
    tasks = []
    if not Path(filepath).exists():
        return tasks

    status_map = {' ': 'pending', '~': 'in_progress', 'x': 'done', '-': 'cancelled'}
    pattern = re.compile(
        r'^- \[([ x~-])\] \*\*(\w+)\*\* (.+?) \| ([\w-]+) \| (.+)$'
    )

    with open(filepath, 'r') as f:
        for line in f:
            match = pattern.match(line.strip())
            if match:
                status_char = match.group(1)
                tasks.append({
                    'text': match.group(3).strip(),
                    'priority': match.group(2).lower(),
                    'category': match.group(4).strip(),
                    'notes': match.group(5).strip(),
                    'status': status_map.get(status_char, 'pending'),
                    'done': status_char == 'x'
                })

    return tasks


@app.route('/api/tasks')
def get_tasks():
    """Get customer open items from OPEN-ITEMS.md"""
    try:
        state = load_task_state()
        tasks = parse_open_items()

        # Apply persisted state
        for t in tasks:
            tid = t['id']
            if tid in state:
                t['status'] = state[tid].get('status', t['status'])

        active = [t for t in tasks if t['status'] not in ('completed', 'skipped')]
        completed_today = sum(1 for s in state.values()
                              if s.get('status') == 'completed'
                              and s.get('date') == datetime.now().strftime('%Y-%m-%d'))
        high = sum(1 for t in active if t['priority'] == 'high')

        return jsonify({
            'success': True,
            'tasks': active,
            'stats': {
                'pending': len(active),
                'completed_today': completed_today,
                'high_priority': high,
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'tasks': []}), 500


@app.route('/api/tasks/<task_id>/complete', methods=['POST'])
def complete_task(task_id):
    state = load_task_state()
    state[task_id] = {'status': 'completed', 'date': datetime.now().strftime('%Y-%m-%d')}
    save_task_state(state)
    return jsonify({'success': True})


@app.route('/api/tasks/<task_id>/skip', methods=['POST'])
def skip_task(task_id):
    state = load_task_state()
    state[task_id] = {'status': 'skipped', 'date': datetime.now().strftime('%Y-%m-%d')}
    save_task_state(state)
    return jsonify({'success': True})


@app.route('/api/tasks/<task_id>/edit', methods=['POST'])
def edit_task(task_id):
    data = request.get_json() or {}
    tasks = parse_open_items()
    task = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    if 'proposed_response' in data:
        task['proposed_response'] = data['proposed_response']
    return jsonify({'success': True, 'task': task})


@app.route('/api/tasks/<task_id>/delete', methods=['POST'])
def delete_task(task_id):
    """Remove task line from OPEN-ITEMS.md permanently"""
    tasks = parse_open_items()
    task = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        return jsonify({'success': False, 'error': 'Not found'}), 404

    target = task['title']
    lines = OPEN_ITEMS_FILE.read_text().splitlines(keepends=True)
    new_lines = [l for l in lines if target not in l]
    OPEN_ITEMS_FILE.write_text(''.join(new_lines))
    return jsonify({'success': True})


@app.route('/api/tasks/<task_id>/approve', methods=['POST'])
def approve_task(task_id):
    state = load_task_state()
    state[task_id] = {'status': 'completed', 'date': datetime.now().strftime('%Y-%m-%d')}
    save_task_state(state)
    return jsonify({'success': True})


@app.route('/api/daily-summary')
def daily_summary():
    try:
        state = load_task_state()
        tasks = parse_open_items()
        active = [t for t in tasks if t['status'] not in ('completed', 'skipped')
                  and t['id'] not in state]
        high = sum(1 for t in active if t['priority'] == 'high')
        completed_today = sum(1 for s in state.values()
                              if s.get('status') == 'completed'
                              and s.get('date') == datetime.now().strftime('%Y-%m-%d'))
        return jsonify({
            'success': True,
            'summary': {
                'date': datetime.now().strftime('%A, %B %d'),
                'emails_pending': 0,
                'high_priority_count': high,
                'pending_tasks': len(active),
                'completed_today': completed_today,
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


CUSTOMER_ALIASES = {
    'NAF (New America Funding)': 'NAF',
}

IGNORE_CUSTOMERS = {'NUOVO', 'Note / Contesto aggiornato', ''}

def normalize_customer(name):
    return CUSTOMER_ALIASES.get(name, name)


@app.route('/api/customers')
def get_customers():
    tasks = parse_open_items()
    customers = {}
    for t in tasks:
        c = normalize_customer(t['customer'])
        if not c or c in IGNORE_CUSTOMERS:
            continue
        if c not in customers:
            customers[c] = {'name': c, 'task_count': 0}
        customers[c]['task_count'] += 1
    ordered = ['Backblaze', 'NAF', 'NM DOH', 'NMC Courts', 'EMNRD', 'Mesa Power']
    result = [customers[c] for c in ordered if c in customers]
    result += [v for k, v in customers.items() if k not in ordered]
    return jsonify({'success': True, 'customers': result})


# ---------------------------------------------------------------------------
# Freshdesk live ticket integration
# ---------------------------------------------------------------------------

FRESHDESK_BASE = "https://versanetworks.freshdesk.com/api/v2"
FRESHDESK_KEY_FILE = DATA_DIR / "freshdesk.key"
CACHE_TTL_SECONDS = 1800  # 30 minutes

# Freshdesk company IDs — only customers that have TAC tickets
FRESHDESK_COMPANY_IDS = {
    'Backblaze': 23000106178,
    'NM DOH': 23000107078,
}

FD_STATUS = {2: 'Open', 3: 'Pending', 4: 'Resolved', 5: 'Closed',
             6: 'Waiting on Customer', 7: 'Waiting on 3rd Party'}
FD_PRIORITY = {1: 'Low', 2: 'Medium', 3: 'High', 4: 'Urgent'}
OPEN_STATUSES = {2, 3, 6, 7}  # exclude Resolved/Closed

_ticket_cache: dict = {}   # name -> {'tickets': [...], 'updated_at': datetime, 'error': str|None}
_cache_lock = threading.Lock()


def _load_fd_key() -> str | None:
    if FRESHDESK_KEY_FILE.exists():
        return FRESHDESK_KEY_FILE.read_text().strip()
    return os.environ.get('FRESHDESK_API_KEY')


def _fd_get(path: str, api_key: str) -> list | dict:
    url = f"{FRESHDESK_BASE}{path}"
    resp = http_requests.get(url, auth=(api_key, 'X'), timeout=15)
    resp.raise_for_status()
    return resp.json()


def _fetch_tickets_for(customer: str, company_id: int, api_key: str) -> list:
    now = datetime.now(timezone.utc)
    tickets = []
    page = 1
    while True:
        data = _fd_get(
            f"/tickets?company_id={company_id}&per_page=100&page={page}&include=requester,stats",
            api_key,
        )
        if not isinstance(data, list) or not data:
            break
        tickets.extend(data)
        if len(data) < 100:
            break
        page += 1

    result = []
    for t in tickets:
        status_code = t.get('status', 2)
        if status_code not in OPEN_STATUSES:
            continue

        overdue = t.get('is_escalated', False)
        status_label = ('⚠️ OVERDUE' if overdue else FD_STATUS.get(status_code, 'Open'))
        priority_label = FD_PRIORITY.get(t.get('priority', 2), 'Medium')
        requester = (t.get('requester') or {}).get('name', 'Unknown')
        stats = t.get('stats') or {}

        # Build a human note from stats
        note = ''
        if stats.get('requester_responded_at'):
            note = 'Customer responded'
        elif stats.get('agent_responded_at'):
            note = 'Agent responded'
        due = t.get('due_by', '')
        if due:
            due_dt = datetime.fromisoformat(due.replace('Z', '+00:00'))
            days = (due_dt - now).days
            if overdue:
                note = f"Overdue by {abs(days)} days" + (f" — {note}" if note else '')
            elif days >= 0 and not note:
                note = f"Due in {days} days"

        result.append({
            'id': t['id'],
            'title': t.get('subject', ''),
            'status': status_label,
            'priority': priority_label,
            'opened_by': requester,
            'note': note,
            'created': t.get('created_at', '')[:10],
            'updated': t.get('updated_at', '')[:10],
        })

    result.sort(key=lambda x: (0 if 'OVERDUE' in x['status'] else 1, x['id']))
    return result


def refresh_ticket_cache(customer: str | None = None):
    api_key = _load_fd_key()
    if not api_key:
        return

    targets = {customer: FRESHDESK_COMPANY_IDS[customer]} if customer else FRESHDESK_COMPANY_IDS

    for name, company_id in targets.items():
        try:
            tickets = _fetch_tickets_for(name, company_id, api_key)
            with _cache_lock:
                _ticket_cache[name] = {
                    'tickets': tickets,
                    'updated_at': datetime.now(timezone.utc),
                    'error': None,
                }
            print(f"[Freshdesk] {name}: {len(tickets)} open tickets cached")
        except Exception as e:
            print(f"[Freshdesk] {name}: fetch error — {e}")
            with _cache_lock:
                if name not in _ticket_cache:
                    _ticket_cache[name] = {'tickets': [], 'updated_at': None, 'error': str(e)}
                else:
                    _ticket_cache[name]['error'] = str(e)


def _background_refresh_loop():
    while True:
        refresh_ticket_cache()
        time.sleep(CACHE_TTL_SECONDS)


@app.route('/api/customers/<customer_name>/tickets')
def get_customer_tickets(customer_name):
    with _cache_lock:
        entry = _ticket_cache.get(customer_name)

    if entry is None and customer_name not in FRESHDESK_COMPANY_IDS:
        return jsonify({'success': True, 'tickets': [], 'total': 0,
                        'note': 'No Freshdesk company on record'})

    if entry is None:
        # First request — fetch synchronously
        refresh_ticket_cache(customer_name)
        with _cache_lock:
            entry = _ticket_cache.get(customer_name, {'tickets': [], 'error': 'Unavailable'})

    tickets = entry.get('tickets', [])
    updated = entry['updated_at'].strftime('%H:%M') if entry.get('updated_at') else None
    return jsonify({
        'success': True,
        'tickets': tickets,
        'total': len(tickets),
        'cached_at': updated,
        'error': entry.get('error'),
    })


@app.route('/api/customers/<customer_name>/tickets/refresh', methods=['POST'])
def force_refresh_tickets(customer_name):
    if customer_name not in FRESHDESK_COMPANY_IDS:
        return jsonify({'success': False, 'error': 'No Freshdesk company on record'}), 404
    threading.Thread(target=refresh_ticket_cache, args=(customer_name,), daemon=True).start()
    return jsonify({'success': True, 'message': 'Refresh triggered'})


@app.route('/api/roadmap')
def get_roadmap():
    customers = [
        {'title': 'Backblaze — Deployment', 'progress': 85},
        {'title': 'NM DOH — Mobile POC', 'progress': 60},
        {'title': 'NAF — SASE POC', 'progress': 45},
        {'title': 'NMC Courts — POC', 'progress': 20},
        {'title': 'EMNRD — AWS POC', 'progress': 30},
        {'title': 'Mesa Power — Qualify', 'progress': 10},
    ]
    return jsonify({
        'success': True,
        'roadmap': {
            'q1_2026': {
                'goals': customers
            }
        }
    })


def parse_draft_file(filepath):
    """Parse a Twitter draft markdown file"""
    content = filepath.read_text()
    meta = {}
    body = content

    # Parse YAML frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    meta[key.strip()] = val.strip()
            body = parts[2].strip()

    return {
        "id": filepath.stem,
        "filename": filepath.name,
        "date": meta.get("date", ""),
        "status": meta.get("status", "draft"),
        "char_count": int(meta.get("char_count", len(body))),
        "scheduled_time": meta.get("scheduled_time", ""),
        "content": body,
    }


@app.route('/api/drafts')
def get_drafts():
    """List all Twitter drafts, scheduled, and posted"""
    result = {"drafts": [], "scheduled": [], "posted": []}

    for folder, key in [
        (TWITTER_DRAFTS, "drafts"),
        (TWITTER_SCHEDULED, "scheduled"),
        (TWITTER_POSTED, "posted"),
    ]:
        if not folder.exists():
            continue
        for f in sorted(folder.glob("*.md"), reverse=True):
            try:
                result[key].append(parse_draft_file(f))
            except Exception:
                continue

    return jsonify(result)


@app.route('/api/drafts/<draft_id>/approve', methods=['POST'])
def approve_draft(draft_id):
    """Move a draft to scheduled folder with optional edit and schedule time"""
    TWITTER_SCHEDULED.mkdir(parents=True, exist_ok=True)

    src = TWITTER_DRAFTS / f"{draft_id}.md"
    if not src.exists():
        return jsonify({"error": "Draft not found"}), 404

    data = request.get_json() or {}
    new_content = data.get("content")
    scheduled_time = data.get("scheduled_time", "")

    # Read existing file
    original = src.read_text()

    if new_content:
        # Rebuild file with updated content
        lines = [
            "---",
            f"date: {datetime.now().strftime('%Y-%m-%d')}",
            "platform: twitter",
            "status: approved",
            f"char_count: {len(new_content)}",
        ]
        if scheduled_time:
            lines.append(f"scheduled_time: {scheduled_time}")
        lines.append("---")
        lines.append("")
        lines.append(new_content)
        file_content = "\n".join(lines)
    else:
        # Just update status in frontmatter
        file_content = original.replace("status: draft", "status: approved")
        if scheduled_time:
            file_content = file_content.replace("---\n\n", f"scheduled_time: {scheduled_time}\n---\n\n", 1)

    dst = TWITTER_SCHEDULED / src.name
    dst.write_text(file_content)
    src.unlink()

    return jsonify({"status": "ok", "message": f"Draft approved and moved to scheduled", "filename": src.name})


@app.route('/api/drafts/<draft_id>/delete', methods=['POST'])
def delete_draft(draft_id):
    """Delete a draft"""
    src = TWITTER_DRAFTS / f"{draft_id}.md"
    if not src.exists():
        return jsonify({"error": "Draft not found"}), 404

    src.unlink()
    return jsonify({"status": "ok", "message": "Draft deleted"})


@app.route('/api/drafts/<draft_id>/edit', methods=['POST'])
def edit_draft(draft_id):
    """Edit a draft's content"""
    src = TWITTER_DRAFTS / f"{draft_id}.md"
    if not src.exists():
        return jsonify({"error": "Draft not found"}), 404

    data = request.get_json() or {}
    new_content = data.get("content")
    if not new_content:
        return jsonify({"error": "No content provided"}), 400

    lines = [
        "---",
        f"date: {datetime.now().strftime('%Y-%m-%d')}",
        "platform: twitter",
        "status: draft",
        f"char_count: {len(new_content)}",
        "---",
        "",
        new_content,
    ]
    src.write_text("\n".join(lines))

    return jsonify({"status": "ok", "char_count": len(new_content)})


if __name__ == '__main__':
    TWITTER_SCHEDULED.mkdir(parents=True, exist_ok=True)
    TWITTER_POSTED.mkdir(parents=True, exist_ok=True)

    # Start Freshdesk background refresh (initial + recurring every 30 min)
    t = threading.Thread(target=_background_refresh_loop, daemon=True)
    t.start()

    print("=" * 60)
    print("SE-Bot Dashboard Server")
    print("=" * 60)
    print(f"Starting on http://localhost:8081")
    freshdesk_key = _load_fd_key()
    print(f"Freshdesk: {'enabled (' + ', '.join(FRESHDESK_COMPANY_IDS.keys()) + ')' if freshdesk_key else 'NO KEY FOUND'}")
    print("=" * 60)

    app.run(host='0.0.0.0', port=8081, debug=True, use_reloader=False)
