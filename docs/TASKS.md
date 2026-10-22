# Tasks

## RomM

- [ ] Add metadata provider API keys to Vault with `vault kv patch secret/homelab/romm` (not `put`), then check that a rescan picks up the new artwork and metadata. See `helm/charts/romm/README.md`.
  - [ ] ScreenScraper: `SCREENSCRAPER_USER`, `SCREENSCRAPER_PASSWORD` (https://www.screenscraper.fr)
  - [ ] RetroAchievements: `RETROACHIEVEMENTS_API_KEY` (https://retroachievements.org/settings)
  - [ ] SteamGridDB: `STEAMGRIDDB_API_KEY` (https://www.steamgriddb.com/profile/preferences/api)
  - [ ] IGDB: `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET` (Twitch app at https://dev.twitch.tv/console/apps)

## Backups (VolSync)

- [ ] Deploy VolSync: commit `helm/charts/volsync`, `helm/charts/volsync-backups` and their `root-app` Applications (`volsync-app.yaml`, `volsync-backups-app.yaml`), along with the `opentofu/backblaze` bucket.
- [ ] Fix `tandoor-pg-dump` in `helm/charts/volsync-backups/values.yaml`: `host: tandoor-recipes-postgres` should be `tandoor-recipes-db` (the live Service name).
- [ ] After the first nightly run, check that `romm-pg-dump` writes `backups/romm-pg-dump.dump` to `romm-data-pvc` and that `backup-romm-data` completes a ReplicationSource sync.
