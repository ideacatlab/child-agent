.PHONY: install dev test lint fmt doctor sentinel autopilot clean

install:        ## install core only (no dependencies)
	pip install -e .

dev:            ## install with everything + dev tools
	pip install -e ".[all,dev]"

test:           ## run the test suite
	pytest -q

lint:           ## lint
	ruff check scion tests

fmt:            ## auto-fix lint
	ruff check --fix scion tests

doctor:         ## check config + dependencies
	scion doctor

sentinel:       ## run the always-on layer (telegram receiver + cron). The BRAIN is
	scion sentinel   ## separate: open Claude Code and run `/loop scion autopilot`.

autopilot:      ## hand-drain one task (what the /loop brain calls each cycle)
	scion autopilot

clean:          ## remove runtime state (keeps your .env)
	find workspace -mindepth 1 -not -name '.gitkeep' -delete
	rm -rf .pytest_cache .ruff_cache **/__pycache__
