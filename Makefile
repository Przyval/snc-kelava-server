REMOTE       := root@104.194.154.108
DEPLOY_DIR   := /root/kil-server
VENV         := $(DEPLOY_DIR)/.venv
PROD_URL     := https://safencare.work

.PHONY: help deploy deploy-full sync restart ssh logs logs-err \
        smoke status health tunnel lint fmt migrate \
        dev install

# ── Default ──────────────────────────────────────────────────────────────────
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Deploy ───────────────────────────────────────────────────────────────────
deploy: lint ## Lint → sync backend + gunicorn config → restart service
	@echo "→ Syncing kil/backend/ ..."
	rsync -avz --delete \
	  --exclude='__pycache__' \
	  --exclude='*.pyc' \
	  --exclude='.DS_Store' \
	  --exclude='*.db' \
	  kil/backend/ $(REMOTE):$(DEPLOY_DIR)/kil/backend/
	rsync -avz gunicorn.conf.py $(REMOTE):$(DEPLOY_DIR)/gunicorn.conf.py
	@echo "→ Restarting kil-api ..."
	ssh $(REMOTE) 'systemctl restart kil-api && sleep 2 && systemctl status kil-api --no-pager'

deploy-full: lint ## Sync entire kil/ (includes db/, rules/, worker/) + restart
	@echo "→ Syncing kil/ ..."
	rsync -avz --delete \
	  --exclude='__pycache__' \
	  --exclude='*.pyc' \
	  --exclude='.DS_Store' \
	  --exclude='*.db' \
	  kil/ $(REMOTE):$(DEPLOY_DIR)/kil/
	ssh $(REMOTE) 'systemctl restart kil-api && sleep 2 && systemctl status kil-api --no-pager'

sync: ## Sync code only (no restart)
	rsync -avz --delete \
	  --exclude='__pycache__' \
	  --exclude='*.pyc' \
	  --exclude='.DS_Store' \
	  --exclude='*.db' \
	  kil/backend/ $(REMOTE):$(DEPLOY_DIR)/kil/backend/

restart: ## Restart service on production
	ssh $(REMOTE) 'systemctl restart kil-api'

# ── Operations ───────────────────────────────────────────────────────────────
ssh: ## SSH into production server
	ssh $(REMOTE)

logs: ## Tail production logs (journalctl -f)
	ssh $(REMOTE) 'journalctl -u kil-api -f --no-pager'

logs-err: ## Tail production error logs only
	ssh $(REMOTE) 'journalctl -u kil-api -p err -n 50 --no-pager'

status: ## Check service status on production
	ssh $(REMOTE) 'systemctl status kil-api --no-pager'

health: ## Hit production health endpoint
	curl -s $(PROD_URL)/api/v1/health | python3 -m json.tool

smoke: ## Run smoke tests against production
	ssh $(REMOTE) '$(VENV)/bin/python3 $(DEPLOY_DIR)/kil/backend/scripts/smoke_test.py'

tunnel: ## SSH tunnel to Kelava DB → localhost:5433
	@echo "→ Tunnel open at localhost:5433 (Kelava DB)"
	ssh -f -N -L 5433:172.104.188.76:5432 $(REMOTE)

# ── Database ─────────────────────────────────────────────────────────────────
migrate: ## Apply pending SQL migrations on production (enterprise DB)
	@echo "→ Running migrations ..."
	@for f in kil/db/migrations/*.sql; do \
	  echo "   $$f"; \
	  ssh $(REMOTE) "psql \$$ENTERPRISE_DB_URL -f $(DEPLOY_DIR)/$$f 2>/dev/null || true"; \
	done

# ── Local Dev ────────────────────────────────────────────────────────────────
dev: ## Start Flask dev server locally (port 5002)
	FLASK_APP=kil.backend.legacy.app \
	FLASK_ENV=development \
	python3 -m flask run --port 5002 --reload

install: ## Install Python deps with uv
	uv pip install -e ".[dev]"

# ── Code Quality ─────────────────────────────────────────────────────────────
lint: ## Run ruff linter
	ruff check kil/

fmt: ## Format code with ruff
	ruff format kil/

fmt-check: ## Check formatting (CI mode)
	ruff format --check kil/
