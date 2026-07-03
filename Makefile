.PHONY: run dev test lint docker-build docker-up docker-down freeze

PYTHON ?= python
PORT ?= 8000

run:
	$(PYTHON) scripts/start.py

dev:
	RELOAD=true DEBUG=true $(PYTHON) scripts/start.py

test:
	$(PYTHON) -m pytest tests/ -q

lint:
	ruff check .

docker-build:
	docker compose build

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

freeze:
	$(PYTHON) -m pip freeze > requirements.txt
