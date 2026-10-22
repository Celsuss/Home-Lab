# RomM

Self-hosted ROM library manager: scans the library, enriches it with metadata
and artwork, and plays games in the browser (EmulatorJS). It is the library
layer of the game stack. Native emulators on the TV PC read the same library
later.

- LAN: https://romm.homelab.local
- Tailnet: https://romm.<tailnet>.ts.net

## Secrets

Secrets are managed via Vault and synced by the Vault Secrets Operator into the
`romm-secrets` Secret, which the deployment loads with `envFrom`. Any RomM env
var stored at this path reaches the pod, and the VaultStaticSecret rolls the
deployment when the path changes.

### Required (before the first sync)
```bash
vault kv put secret/homelab/romm \
  POSTGRES_PASSWORD="$(openssl rand -hex 24)" \
  ROMM_AUTH_SECRET_KEY="$(openssl rand -hex 32)"
```

Postgres only reads `POSTGRES_PASSWORD` when it initialises an empty data dir,
so do not rotate it afterwards without also running `ALTER USER` in the DB.

### Optional metadata providers

Hasheous and LaunchBox are on by default and need no account. Add keys with
`vault kv patch` (not `put`, which would drop the keys above). Use only the
ones you have registered for:

```bash
vault kv patch secret/homelab/romm \
  SCREENSCRAPER_USER="your-screenscraper-user" \
  SCREENSCRAPER_PASSWORD="your-screenscraper-password" \
  RETROACHIEVEMENTS_API_KEY="your-ra-web-api-key" \
  STEAMGRIDDB_API_KEY="your-steamgriddb-key" \
  IGDB_CLIENT_ID="your-twitch-client-id" \
  IGDB_CLIENT_SECRET="your-twitch-client-secret"
```

- ScreenScraper: account at https://www.screenscraper.fr
- RetroAchievements: https://retroachievements.org/settings (Web API Key)
- SteamGridDB: https://www.steamgriddb.com/profile/preferences/api
- IGDB: Twitch developer app at https://dev.twitch.tv/console/apps

## Adding ROMs

The library PVC is mounted at `/romm/library` and uses RomM's default layout:
`roms/<platform-slug>/<game file or folder>`. Platform slugs are listed at
https://docs.romm.app/latest/Platforms-and-Players/Supported-Platforms/
(e.g. `snes`, `n64`, `gba`, `psx`, `ps2`, `ngc`).

Either upload through the web UI (Upload in the sidebar), or copy straight into
the local-path directory on the node:

```bash
LIB="$(sudo find /var/lib/rancher/k3s/storage -maxdepth 1 -name '*_games_romm-library-pvc')"
sudo mkdir -p "$LIB/roms/snes"
sudo cp ~/ROMs/snes/*.sfc "$LIB/roms/snes/"
```

Then run a scan from the UI. The nightly scheduled rescan (03:00) also picks
new files up.

BIOS files go in `roms/<platform-slug>/bios/` or are uploaded per platform in the UI.

## Backups

`volsync-backups` covers `romm-data-pvc` (covers, uploaded saves and states,
config.yml, and the nightly `romm-pg-dump` in `backups/`). The ROM library PVC
is **not** backed up, so keep the originals somewhere else.

## Kanidm SSO (optional)

Off by default (`oidc.enabled: false`). Username/password login keeps working
when SSO is on, and it has to: `*.homelab.local` never resolves for devices on
the tailnet, so SSO only works on the LAN.

1. Create the OAuth2 client and groups in Kanidm:
   ```bash
   kanidm system oauth2 create romm "RomM" https://romm.homelab.local
   kanidm system oauth2 add-redirect-url romm https://romm.homelab.local/api/oauth/openid
   kanidm group create romm_users
   kanidm group create romm_admins
   kanidm group add-members romm_users idm_admin
   kanidm group add-members romm_admins idm_admin
   kanidm system oauth2 update-scope-map romm romm_users openid profile email groups
   kanidm system oauth2 show-basic-secret romm
   ```
   Replace `idm_admin` with your own Kanidm username.
2. Store the secret:
   ```bash
   vault kv patch secret/homelab/romm OIDC_CLIENT_SECRET="$(kanidm system oauth2 show-basic-secret romm)"
   ```
3. Set `oidc.enabled: true` in `values.yaml` and push.

Members of `romm_admins` become RomM admins. Everyone else in `romm_users`
becomes a viewer (`oidc.roleViewer: "*"`).
