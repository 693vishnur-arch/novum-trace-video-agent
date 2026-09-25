.PHONY: run test smoke

run:
	uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest -q

smoke:
	python -m compileall backend
