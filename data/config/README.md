# Persistent configuration

This directory lives under your `FACTORY_DATA` mount at `/data/config` inside the container.

| File | Purpose |
|------|---------|
| `encryption.key` | Auto-generated on first boot; required to decrypt stored secrets |
| `local.env` | Optional overrides (copy from `local.env.example`) |

Dashboard settings (preview host, API key, Cursor connection) are stored in PostgreSQL under `${FACTORY_DATA}/postgres/`.

**Back up** `${FACTORY_DATA}/config` and `${FACTORY_DATA}/postgres/` before major upgrades.
