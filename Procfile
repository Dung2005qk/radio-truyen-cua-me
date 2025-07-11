web: gunicorn --bind 0.0.0.0:$PORT --workers 3 --log-level=info app:app
worker: python cleanup.py