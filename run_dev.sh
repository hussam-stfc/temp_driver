#!/bin/bash
# Development environment startup script
# Layouts: driver (top, full width), db_server (bottom-left), softIoc (bottom-right)

set -e

SESSION="devenv"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"

# Kill existing session if it exists
tmux kill-session -t $SESSION 2>/dev/null || true

# Create new session (initial pane will be top - for driver)
tmux new-session -d -s $SESSION -x 200 -y 50

# Split vertically to create top/bottom
tmux split-window -t $SESSION -v

# Select bottom pane and split horizontally (for db_server and softIoc)
tmux select-pane -t $SESSION.1
tmux split-window -t $SESSION -h

# Send driver to top pane (pane 0)
tmux select-pane -t $SESSION.0
tmux send-keys -t $SESSION "cd '$REPO_ROOT/driver' && '$VENV_PYTHON' driver.py" Enter

# Send db_server to bottom-left pane (pane 1)
tmux select-pane -t $SESSION.1
tmux send-keys -t $SESSION "cd '$REPO_ROOT/db_server' && '$VENV_PYTHON' -m uvicorn serve_db:app --reload" Enter

# Send softIoc to bottom-right pane (pane 2)
tmux select-pane -t $SESSION.2
tmux send-keys -t $SESSION "cd '$REPO_ROOT' &&softIoc -d state.db" Enter

# Attach to session
tmux attach -t $SESSION
