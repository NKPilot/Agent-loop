.PHONY: backend frontend start stop restart status install dev clean demo test test-all

PID_DIR := .pids

# ── 安装 ──────────────────────────────────────────────────────────

install:
	uv sync --extra dev
	uv pip install -e .
	cd frontend && pnpm install

# ── 开发模式（前台运行，推荐）─────────────────────────────────────

dev: install
	@echo "启动开发模式..."
	@echo "  后端: http://localhost:8000"
	@echo "  前端: http://localhost:5173"
	@echo "  按 Ctrl+C 停止所有服务"
	@trap 'kill 0' EXIT; \
		uv run uvicorn loopai.api.app:create_app --factory --host 0.0.0.0 --port 8000 & \
		cd frontend && pnpm dev & \
		wait

# ── 后台启动 ──────────────────────────────────────────────────────

start:
	@mkdir -p $(PID_DIR)
	@echo "启动后端..."
	@nohup uv run uvicorn loopai.api.app:create_app --factory --host 0.0.0.0 --port 8000 \
		> /tmp/loopai-backend.log 2>&1 & echo $$! > $(PID_DIR)/backend.pid
	@echo "  后端 PID: $$(cat $(PID_DIR)/backend.pid)"
	@echo "启动前端..."
	@cd frontend && nohup pnpm dev > /tmp/loopai-frontend.log 2>&1 & echo $$! > ../../$(PID_DIR)/frontend.pid
	@echo "  前端 PID: $$(cat $(PID_DIR)/frontend.pid)"
	@echo "日志: /tmp/loopai-backend.log /tmp/loopai-frontend.log"

# ── 停止 ──────────────────────────────────────────────────────────

stop:
	@echo "停止服务..."
	@-test -f $(PID_DIR)/backend.pid && kill $$(cat $(PID_DIR)/backend.pid) 2>/dev/null && echo "  后端已停止" || true
	@-test -f $(PID_DIR)/frontend.pid && kill $$(cat $(PID_DIR)/frontend.pid) 2>/dev/null && echo "  前端已停止" || true
	@-pkill -f "uvicorn loopai.api.app" 2>/dev/null || true
	@-pkill -f "vite" 2>/dev/null || true
	@rm -f $(PID_DIR)/*.pid
	@echo "完成"

# ── 重启 ──────────────────────────────────────────────────────────

restart: stop start

# ── 状态 ──────────────────────────────────────────────────────────

status:
	@echo "=== loopAI 服务状态 ==="
	@echo -n "后端 (port 8000): "
	@curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost:8000/api/sessions 2>/dev/null || echo "未运行"
	@echo ""
	@echo -n "前端 (port 5173): "
	@curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost:5173 2>/dev/null || echo "未运行"
	@echo ""

# ── 测试 ──────────────────────────────────────────────────────────

test:
	uv run pytest tests/ -q --ignore=tests/api

test-all:
	uv run pytest tests/ -q

# ── 演示场景 ──────────────────────────────────────────────────────

demo:
	bash scripts/setup_demo_scenario.sh
	@echo "场景就绪，运行: make dev"

# ── 清理 ──────────────────────────────────────────────────────────

clean:
	rm -rf $(PID_DIR) .sandbox logs/sessions/*
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "清理完成"
