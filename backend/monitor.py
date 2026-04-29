#!/usr/bin/env python3
"""
SE-Bot Monitoring System
Collects metrics from all automated systems and stores in JSON
"""

import os
import json
import subprocess
from datetime import datetime
from pathlib import Path

# Paths
SE_BOT_ROOT = Path("/Users/mattia/SE-Bot")
DASHBOARD_DATA = SE_BOT_ROOT / "dashboard" / "data"
METRICS_FILE = DASHBOARD_DATA / "metrics.json"
STATUS_FILE = DASHBOARD_DATA / "status.json"

# Projects to monitor
PROJECTS = {
    "social_content": {
        "name": "Social Content Generator",
        "script": SE_BOT_ROOT / "social" / "generate_content_v2.py",
        "log": SE_BOT_ROOT / "social" / "content-generator.log",
        "drafts_twitter": SE_BOT_ROOT / "social" / "content" / "twitter" / "drafts",
        "drafts_linkedin": SE_BOT_ROOT / "social" / "content" / "linkedin" / "drafts",
        "schedule": "Mon-Fri 7:00 AM",
        "launchagent": "com.sebot.socialcontent"
    },
    "telegram_bot": {
        "name": "Telegram Bot",
        "script": SE_BOT_ROOT / "telegram-bot" / "bot.py",
        "log": SE_BOT_ROOT / "telegram-bot" / "bot.log",
        "schedule": "Always running",
        "launchagent": None  # Manual run
    },
    "slack_polling": {
        "name": "Slack Polling Bot",
        "script": SE_BOT_ROOT / "telegram-bot" / "slack_polling_bot.py",
        "log": SE_BOT_ROOT / "telegram-bot" / "slack-polling.log",
        "schedule": "Every 15 seconds",
        "launchagent": "com.sebot.slackpolling"
    },
    "daily_briefing": {
        "name": "Daily Briefing",
        "script": SE_BOT_ROOT / "telegram-bot" / "generate_briefing_pdf.py",
        "log": SE_BOT_ROOT / "telegram-bot" / "briefing.log",
        "schedule": "Daily 1:00 PM (Mon-Fri)",
        "launchagent": "com.sebot.dailybriefing"
    }
}


def ensure_data_dir():
    """Create data directory if it doesn't exist"""
    DASHBOARD_DATA.mkdir(parents=True, exist_ok=True)


def check_launchagent_status(agent_name):
    """Check if LaunchAgent is running"""
    if not agent_name:
        return {"status": "manual", "message": "Not scheduled"}

    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if agent_name in result.stdout:
            # Parse PID (if running)
            for line in result.stdout.split('\n'):
                if agent_name in line:
                    parts = line.split()
                    pid = parts[0]
                    if pid == "-":
                        return {"status": "loaded", "message": "Loaded but not running (waiting for schedule)"}
                    else:
                        return {"status": "running", "pid": pid, "message": f"Running (PID: {pid})"}

        return {"status": "not_loaded", "message": "Not loaded"}

    except Exception as e:
        return {"status": "error", "message": f"Error checking status: {e}"}


def get_log_tail(log_file, lines=10):
    """Get last N lines from log file"""
    if not log_file or not Path(log_file).exists():
        return []

    try:
        with open(log_file, 'r') as f:
            return f.readlines()[-lines:]
    except Exception as e:
        return [f"Error reading log: {e}"]


def get_log_errors(log_file, hours=24):
    """Count errors in log file from last N hours"""
    if not log_file or not Path(log_file).exists():
        return 0

    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()

        error_count = 0
        error_keywords = ['error', 'exception', 'failed', 'traceback']

        for line in lines:
            if any(keyword in line.lower() for keyword in error_keywords):
                error_count += 1

        return error_count

    except Exception:
        return 0


def count_files_in_directory(directory):
    """Count files in a directory"""
    if not directory or not Path(directory).exists():
        return 0

    try:
        return len([f for f in Path(directory).iterdir() if f.is_file()])
    except Exception:
        return 0


def get_last_run_time(log_file):
    """Extract last run timestamp from log"""
    if not log_file or not Path(log_file).exists():
        return None

    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()

        # Look for timestamp patterns like [2026-01-08 14:22:48]
        import re
        timestamp_pattern = r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]'

        for line in reversed(lines):
            match = re.search(timestamp_pattern, line)
            if match:
                return match.group(1)

        return None

    except Exception:
        return None


def collect_project_metrics(project_id, project_config):
    """Collect metrics for a specific project"""
    metrics = {
        "id": project_id,
        "name": project_config["name"],
        "schedule": project_config["schedule"],
        "last_checked": datetime.now().isoformat(),
    }

    # Check LaunchAgent status
    if project_config.get("launchagent"):
        agent_status = check_launchagent_status(project_config["launchagent"])
        metrics["agent_status"] = agent_status["status"]
        metrics["agent_message"] = agent_status["message"]
        if "pid" in agent_status:
            metrics["pid"] = agent_status["pid"]
    else:
        metrics["agent_status"] = "manual"
        metrics["agent_message"] = "Manual execution"

    # Get last run time
    last_run = get_last_run_time(project_config.get("log"))
    if last_run:
        metrics["last_run"] = last_run
    else:
        metrics["last_run"] = "Never / Unknown"

    # Count errors
    error_count = get_log_errors(project_config.get("log"))
    metrics["error_count_24h"] = error_count
    metrics["health"] = "healthy" if error_count == 0 else ("warning" if error_count < 5 else "error")

    # Project-specific metrics
    if project_id == "social_content":
        metrics["twitter_drafts"] = count_files_in_directory(project_config.get("drafts_twitter"))
        metrics["linkedin_drafts"] = count_files_in_directory(project_config.get("drafts_linkedin"))
        metrics["total_drafts"] = metrics["twitter_drafts"] + metrics["linkedin_drafts"]

    # Get recent log lines
    metrics["recent_logs"] = get_log_tail(project_config.get("log"), lines=5)

    return metrics


def collect_system_metrics():
    """Collect overall system metrics"""
    return {
        "timestamp": datetime.now().isoformat(),
        "uptime": "System running",  # Could enhance with actual uptime
        "projects_monitored": len(PROJECTS),
        "git_status": get_git_status()
    }


def get_git_status():
    """Get Git repository status"""
    try:
        os.chdir(SE_BOT_ROOT)

        # Check if clean
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.stdout.strip():
            uncommitted = len(result.stdout.strip().split('\n'))
            return {
                "status": "uncommitted_changes",
                "count": uncommitted,
                "message": f"{uncommitted} uncommitted changes"
            }
        else:
            return {
                "status": "clean",
                "message": "Working directory clean"
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error: {e}"
        }


def generate_status_summary():
    """Generate human-readable status summary"""
    try:
        with open(METRICS_FILE, 'r') as f:
            data = json.load(f)

        healthy = sum(1 for p in data["projects"].values() if p.get("health") == "healthy")
        total = len(data["projects"])
        warnings = sum(1 for p in data["projects"].values() if p.get("health") == "warning")
        errors = sum(1 for p in data["projects"].values() if p.get("health") == "error")

        summary = {
            "overall_health": "healthy" if errors == 0 and warnings == 0 else ("warning" if errors == 0 else "error"),
            "timestamp": data["system"]["timestamp"],
            "projects_healthy": healthy,
            "projects_total": total,
            "projects_warning": warnings,
            "projects_error": errors,
            "message": f"{healthy}/{total} projects healthy"
        }

        return summary

    except Exception as e:
        return {
            "overall_health": "error",
            "message": f"Error generating summary: {e}"
        }


def main():
    """Main monitoring loop"""
    print("=" * 60)
    print("SE-Bot Monitoring System")
    print("=" * 60)

    ensure_data_dir()

    # Collect metrics from all projects
    print("\nCollecting metrics from all projects...")
    project_metrics = {}

    for project_id, project_config in PROJECTS.items():
        print(f"  Checking {project_config['name']}...")
        metrics = collect_project_metrics(project_id, project_config)
        project_metrics[project_id] = metrics

        # Print summary
        print(f"    Status: {metrics['agent_status']}")
        print(f"    Last Run: {metrics['last_run']}")
        print(f"    Health: {metrics['health']} ({metrics['error_count_24h']} errors)")

        if project_id == "social_content":
            print(f"    Drafts: {metrics['total_drafts']} total ({metrics['twitter_drafts']} Twitter, {metrics['linkedin_drafts']} LinkedIn)")

    # Collect system metrics
    print("\nCollecting system metrics...")
    system_metrics = collect_system_metrics()
    print(f"  Git Status: {system_metrics['git_status']['message']}")

    # Save metrics
    data = {
        "system": system_metrics,
        "projects": project_metrics
    }

    with open(METRICS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\nMetrics saved to: {METRICS_FILE}")

    # Generate status summary
    summary = generate_status_summary()

    with open(STATUS_FILE, 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"Status summary saved to: {STATUS_FILE}")

    # Print overall health
    print("\n" + "=" * 60)
    print(f"OVERALL HEALTH: {summary['overall_health'].upper()}")
    print(f"{summary['message']}")
    if summary['projects_warning'] > 0:
        print(f"⚠️  {summary['projects_warning']} projects with warnings")
    if summary['projects_error'] > 0:
        print(f"❌ {summary['projects_error']} projects with errors")
    print("=" * 60)

    return 0 if summary['overall_health'] in ['healthy', 'warning'] else 1


if __name__ == "__main__":
    try:
        exit(main())
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
