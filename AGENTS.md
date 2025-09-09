# Repository Guidelines

## Project Structure & Module Organization
- `photo_dog.py`: Main CLI crawler for gallery pages (`displayimage.php`).
- `fotos/`: Local images/scratch folder (not required by the tool).
- Default downloads go to `downloads_myphotos/` (configurable via `--out`).
- Consider future split to `photo_dog/` package (e.g., `crawler.py`, `parsers.py`) and `tests/`.

## Build, Test, and Development Commands
- Setup env: `python3 -m venv .venv && source .venv/bin/activate`
- Install deps: `pip install -U requests beautifulsoup4`
- Run locally (example):
  - `python photo_dog.py --start 100 --end 120` 
  - With custom base: `python photo_dog.py --base https://example.com/displayimage.php --start 1 --max-misses 25 --delay 1.5`

## Coding Style & Naming Conventions
- Python, 4 spaces, PEP 8. Keep lines reasonable (~100–120 cols).
- Names: functions/variables `snake_case`; constants `UPPER_SNAKE`; modules `lower_snake`.
- Imports: stdlib, third‑party, local (grouped). Add minimal docstrings for public functions.
- When refactoring, keep CLI behavior and flags backward‑compatible.

## Testing Guidelines
- Framework: `pytest` (recommended). Layout: `tests/test_*.py`.
- Focus: `extract_image_url_from_html`, `guess_ext`, and `crawl` request flow (mock `requests`).
- Run: `pytest -q`; coverage (optional): `pytest --cov=photo_dog.py`.
- Add fixtures for sample HTML pages covering direct image, og:image, and anchor fallbacks.

## Commit & Pull Request Guidelines
- Commits: concise, imperative subject; include rationale in body when needed. Reference issues with `#123`.
- PRs: clear description, steps to reproduce, before/after behavior, and screenshots/logs when relevant.
- Include examples of CLI invocations used for manual testing.

## Security & Configuration Tips
- Be polite to remote servers: tune `--delay`, `--max-misses`; avoid aggressive crawling.
- Respect site terms and robots. Do not commit secrets or cookies.
- If adding headers or auth, read from env vars and document them.
