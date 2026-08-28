# Heyu Agent 单机部署便捷命令
# 用法: make up / make build / make down / make logs / make ps / make db-migrate

COMPOSE := docker compose

.PHONY: up build down logs ps db-migrate

up: build
	$(COMPOSE) up -d

build:
	$(COMPOSE) build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

db-migrate:
	$(COMPOSE) exec backend python -m alembic -c /app/alembic.ini upgrade head
