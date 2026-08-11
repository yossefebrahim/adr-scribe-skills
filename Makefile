PY ?= python3
export PYTHONPATH := skills/adr/scripts

test:
	$(PY) -m unittest discover -s tests -t . -v

lint:
	$(PY) -m compileall -q skills/adr/scripts/adr_scribe
	$(PY) -m compileall -q tests

# Validates SKILL.md against the Agent Skills spec rules we rely on:
# name matches the directory, description present and within limits, and the
# body stays small enough for cheap activation.
check-skill:
	@$(PY) tools/check_skill.py skills/adr

.PHONY: test lint check-skill
