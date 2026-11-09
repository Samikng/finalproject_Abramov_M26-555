install:
	uv sync

project:
	uv run project

build:
	uv build

publish:
	uv publish --dry-run

package-install:
	uv tool install dist/*.whl

lint:
	uv run ruff check .

.PHONY: install project build publish package-install lint
