.PHONY: install test serve clean

install:
	@bash ./install.sh

test:
	@pytest -v tests

serve:
	@vjarvis serve --host 127.0.0.1 --port 8000

clean:
	@rm -rf build dist *.egg-info .pytest_cache
	@find . -type d -name __pycache__ -exec rm -rf {} +
