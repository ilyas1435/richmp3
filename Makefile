.PHONY: test lint install dry-run

test:
	python3 -m unittest discover -s tests -v

lint:
	python3 -m pyflakes richmp3 tests

install:
	python3 -m pip install -e .

dry-run:
	python3 -m richmp3 --dry-run $(URL)
