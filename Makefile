APP_DIR ?= /home/ubuntu/DXSB_lingonberry
SERVER ?= ubuntu@84.8.249.139
SSH_KEY ?= ./ssh-key-2026-02-21.key
BRANCH ?= main

.PHONY: test planner-sync planner-report server-update server-install-services

test:
	python3 -m pytest -q tests/test_planner_v2.py tests/test_regime_intelligence.py tests/test_phase_16.py tests/test_e2e_telegram.py

planner-sync:
	python3 cli.py portfolio sync

planner-report:
	python3 cli.py report daily

server-update:
	ssh -i $(SSH_KEY) $(SERVER) 'cd $(APP_DIR) && git fetch origin && git checkout $(BRANCH) && git pull --ff-only origin $(BRANCH) && source .venv/bin/activate && pip install -r requirements.txt'

server-install-services:
	ssh -i $(SSH_KEY) $(SERVER) 'cd $(APP_DIR) && chmod +x scripts/planner_cycle.sh scripts/install_planner_systemd.sh && APP_DIR=$(APP_DIR) LINUX_USER=$${USER} ./scripts/install_planner_systemd.sh'
