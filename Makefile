.PHONY: install dev test lint fmt doctor chat serve clean

install:        ## install core only
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

chat:           ## interactive chat
	scion chat

serve:          ## run the autonomy stack (worker + scheduler + bot)
	scion serve

clean:          ## remove runtime state (keeps your .env)
	find workspace -mindepth 1 -not -name '.gitkeep' -delete
	rm -rf .pytest_cache .ruff_cache **/__pycache__
