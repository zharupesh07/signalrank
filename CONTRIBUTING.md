# Contributing

Thanks for helping improve SignalRank.

## Development Setup

```bash
./signalrank/setup.sh
```

For targeted setup, see:

- [Backend README](signalrank/backend/README.md)
- [Frontend README](signalrank/frontend/README.md)
- [Desktop README](signalrank/desktop/README.md)

## Checks

Run the narrow checks for the area you changed:

```bash
cd signalrank/backend && uv run pytest
cd signalrank/frontend && npm run check
cd signalrank/desktop && npm run build
```

## Pull Requests

- Keep changes scoped to one concern.
- Include tests for behavioral changes.
- Do not commit real resumes, API keys, `.env` files, database dumps, generated
  benchmark snapshots, or local job-search outputs.
- Prefer synthetic fixtures when adding examples or tests.

## Coding Style

- Python uses Black/Ruff conventions with 88-character lines.
- Frontend code should pass the existing TypeScript and ESLint checks.
- Add comments only when the logic is not obvious from the code.
