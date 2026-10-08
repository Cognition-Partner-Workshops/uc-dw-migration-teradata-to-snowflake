.PHONY: demo up down reset logs test lint

demo up:          ## start everything (web http://localhost:3000, api http://localhost:8000/docs)
	docker compose up --build -d && docker compose ps

down:
	docker compose down

reset:            ## wipe emulator, control DB and simulated warehouses
	docker compose down -v

logs:
	docker compose logs -f api

test:
	cd backend && python -m pytest -q

lint:
	cd backend && ruff check . && ruff format --check .
