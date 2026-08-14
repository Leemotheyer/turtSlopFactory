# Persistent configuration

This directory is bind-mounted into the factory container at `/data/factory`.

| File | Purpose |
|------|---------|
| `encryption.key` | Auto-generated on first boot; required to decrypt stored secrets |
| `local.env` | Optional overrides (copy from `local.env.example`) |

Dashboard settings (preview host, API key, Cursor connection) are stored in PostgreSQL under `./data/postgres/`.

**Back up** this folder and `./data/postgres/` before major upgrades.
