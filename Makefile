.PHONY: sync test lint api web engine-image

sync:
	uv sync --all-packages

test:
	uv run pytest -q

lint:
	uv run ruff check .

api:
	uv run uvicorn modeler_api.main:app --reload

web:
	cd apps/web && npm install && npm run dev

engine-image:
	docker build -f services/engine-worker/Dockerfile -t modeler-engine:dev .
