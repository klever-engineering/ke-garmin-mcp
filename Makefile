PYTHON := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: bootstrap lock test run-cli run-mcp docker-build docker-run verify-outputs

bootstrap:
	./scripts/bootstrap.sh

# Re-resolve uv.lock from pyproject.toml and regenerate requirements.txt.
# Never edit requirements.txt by hand.
lock:
	uv lock
	uv export --quiet --format requirements-txt --no-emit-project --no-dev -o requirements.txt

# Unit tests. Override PYTHON in CI (e.g. `make test PYTHON=python`).
test:
	LIFEOS_OTEL_DISABLE_OTLP=1 PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

run-cli:
	PYTHONPATH=src $(PYTHON) -m garmin_mcp.cli --help

run-mcp:
	./scripts/mcp_stdio.sh

docker-build:
	docker build -t lifeos.garmin-mcp:local .

docker-run:
	docker run -i --rm --env-file .env -e GARMIN_TOKENS_DIR=/data/config/garmin-mcp/tokens -v "$(PWD)/../../../config:/data/config" lifeos.garmin-mcp:local --transport stdio

# Observe whether the Track's LifeOS expected outputs are accomplished (read-only).
verify-outputs:
	python3 scripts/verify_expected_outputs.py
