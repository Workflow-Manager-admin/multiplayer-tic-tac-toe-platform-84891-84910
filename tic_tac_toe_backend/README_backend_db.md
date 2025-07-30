# Tic Tac Toe Backend – Database Integration

## DB Configuration

This FastAPI backend uses SQLAlchemy for persistence. The database URL is read from the environment variable `TICTACTOE_DB_URL`.
- By default (for development), it uses SQLite: `sqlite:///./tic_tac_toe.db`.
- On deployment, set the `TICTACTOE_DB_URL` environment variable to point to your persistent database (e.g., Postgres, MySQL, etc).

## Models

- **Player** table: Stores users. (`id`, `username`)
- **Game** table: Stores game boards and state, player associations, and results.

## Integration

- The backend expects an operational and accessible database at the provided URL.
- On first run, the backend will auto-create tables if not present.
- All game state and user info are persisted to enable session resumption and history.

## Env variable required

- `TICTACTOE_DB_URL`

## Dependency

- This backend expects an external database service (e.g., 'tic_tac_toe_database'), accessible per the environment variable.

---
