PY ?= python3
export PYTHONPATH := skills/adr/scripts

test:
	$(PY) -m unittest discover -s tests -t . -v

lint:
	$(PY) -m compileall -q skills/adr/scripts/adr_scribe

.PHONY: test lint
