web: python -c "import os; port = os.environ.get('PORT', '8000'); os.execvp('gunicorn', ['gunicorn', 'config.wsgi:application', '--bind', f'0.0.0.0:{port}', '--workers', '3'])"
