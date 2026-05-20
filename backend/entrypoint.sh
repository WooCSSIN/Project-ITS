#!/bin/sh
set -e

# Start Discord bot in the background
if [ -f "bot_discord.py" ]; then
  echo "Khởi động Discord bot..."
  python -u bot_discord.py &
fi

# Clear stale Python bytecode caches so mounted files take effect immediately
find /backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Debug: print actual config values used at runtime
python -c "
import sys; sys.path.insert(0, '/backend/app')
from core.config import settings_server
print('=== RUNTIME CONFIG DEBUG ===')
print('DATABASE_URL:', settings_server.DATABASE_URL)
print('============================')
"

# Start FastAPI (uvicorn)
echo "Bắt đầu máy chủ FastAPI..."
export PYTHONPATH=/backend/app:$PYTHONPATH
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws wsproto