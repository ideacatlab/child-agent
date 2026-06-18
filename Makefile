.PHONY: install dev test lint fmt doctor daemon autopilot fleet clean

install:        ## install core only (no dependencies)
	pip install -e .

dev:            ## install with everything + dev tools
	pip install -e ".[all,dev]"

test:           ## run the test suite
	pytest -q

lint:           ## lint
	ruff check agent tests

fmt:            ## auto-fix lint
	ruff check --fix agent tests

doctor:         ## check config + dependencies + the fleet
	agent doctor

daemon:         ## run the always-on layer (telegram receiver + cron + supervision).
	agent daemon    ## The ORCHESTRATOR is separate: open Claude Code, run `/loop agent autopilot`.

autopilot:      ## hand-drain one task (what the /loop orchestrator calls each cycle)
	agent autopilot

fleet:          ## list the agent roles this runtime can spawn
	agent fleet roles

clean:          ## remove runtime state (keeps your .env)
	find workspace -mindepth 1 -not -name '.gitkeep' -delete
	rm -rf .pytest_cache .ruff_cache **/__pycache__
