#!/bin/bash

# 用法: ./scripts/revision.sh -m "your message"
uv run alembic revision --autogenerate "$@"