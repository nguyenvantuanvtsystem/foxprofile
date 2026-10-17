#!/bin/bash
# FoxProfile — mở app quản lý profile (1 click).
# Khởi động server nếu chưa chạy rồi mở web panel.
cd "$HOME/foxprofile" || exit 1
if ! curl -s --max-time 2 http://127.0.0.1:8000/api/v1/profiles > /dev/null 2>&1; then
  echo "Đang khởi động FoxProfile..."
  nohup "$HOME/foxprofile/.venv/bin/python" -m src.server > "$HOME/foxprofile/server.log" 2>&1 &
  for i in $(seq 1 20); do
    sleep 1
    curl -s --max-time 2 http://127.0.0.1:8000/api/v1/profiles > /dev/null 2>&1 && break
  done
fi
open http://127.0.0.1:8000/
echo "FoxProfile: http://127.0.0.1:8000/"
