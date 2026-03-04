PYTHON := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: bootstrap run-cli run-mcp docker-build docker-run

bootstrap:
	./scripts/bootstrap.sh

run-cli:
	PYTHONPATH=src $(PYTHON) -m garmin_mcp.cli --help

run-mcp:
	./scripts/mcp_stdio.sh

docker-build:
	docker build -t lifeos.garmin-mcp:local .

docker-run:
	docker run -i --rm --env-file .env -e GARMIN_TOKENS_DIR=/data/garmin-tokens -v "$(PWD)/.state:/data" lifeos.garmin-mcp:local --transport stdio

