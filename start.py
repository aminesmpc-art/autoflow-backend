"""Railway startup script — Python-based to avoid Windows CRLF issues with bash."""
import os
import subprocess
import sys


def run(cmd):
    print(f"=== {cmd} ===")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"Command failed: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    # Run migrations
    run("python manage.py migrate --noinput --verbosity 1")

    # Collect static files
    run("python manage.py collectstatic --noinput")

    # Ensure superuser exists
    run("python manage.py ensure_superuser")

    # Auto-expire time-limited Pro (reward users, stale grants)
    print("=== Expiring time-limited Pro access ===")
    subprocess.run("python manage.py expire_pro", shell=True)

    # Start gunicorn
    port = os.environ.get("PORT", "8000")
    print(f"=== Starting gunicorn on port {port} ===")
    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            "config.wsgi:application",
            "--bind", f"0.0.0.0:{port}",
            "--workers", "3",
            "--timeout", "120",
        ],
    )
