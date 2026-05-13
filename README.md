# spectre

Automatically find HUD disabling cheats in games emulated on dolphin

## Development

### Pre-commit

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

### Running tests

```bash
uv run pytest
```

**Useful pytest flags:**
- `-v` — verbose output, shows individual test names
- `-s` — show print statements and logs during tests

### Type checking

```bash
uv run mypy src/
```

## Configuration

All config via environment variables — see `.env.example`.
