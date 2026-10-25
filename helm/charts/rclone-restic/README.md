# rclone-restic

restic REST gateway for VolSync. `rclone serve restic` speaks restic's REST
protocol inside the cluster and stores the repositories in Google Drive under
`homelab-backups/<backup-name>/`. The VolSync movers (configured by the
`volsync-backups` chart) reach it at
`rest:http://rclone-restic.volsync-system.svc.cluster.local:8080/<name>/`.

restic encrypts everything before it leaves the mover pod, so Drive only
stores ciphertext. Design and trade-offs:
`docs/plans/2026-10-25-volsync-google-drive.md`.

No ingress: the gateway is only used from inside the cluster.

## Google setup (one-time)

Google can't create consent screens or Desktop OAuth clients for personal
accounts through an API, so this step is manual.

1. [console.cloud.google.com](https://console.cloud.google.com): create a
   project and enable the **Google Drive API**.
2. **Google Auth Platform** (formerly "OAuth consent screen") → Get started:
   - Audience: **External**.
   - **Branding**: home page `https://lorden.dev/`, privacy policy
     `https://lorden.dev/privacy`, authorized domain `lorden.dev`. Leave the
     logo empty, because uploading one forces verification.
   - **Data Access**: add scope `https://www.googleapis.com/auth/drive.file`.
     rclone then only sees files it created.
   - **Audience** → **Publish app**. *Testing* apps get refresh tokens that
     expire after 7 days, and backups stop silently.
   - **Clients** → Create client → **Desktop app**. Note the ID and secret.
3. On a machine with a browser:
   ```bash
   rclone authorize "drive" "<client_id>" "<client_secret>"
   ```
   Click through "unverified app" (Advanced → Go to …). It prints the token
   JSON.

## Vault

The gateway and the movers read two different Vault paths, but they must
share the same REST login:

| Path | Read by | Keys |
|---|---|---|
| `secret/homelab/rclone-gdrive` | this gateway only | `CLIENT_ID`, `CLIENT_SECRET`, `TOKEN`, `REST_USER`, `REST_PASS` |
| `secret/homelab/volsync` | every mover, synced into each backed-up namespace | `RESTIC_PASSWORD`, `RESTIC_REST_USERNAME`, `RESTIC_REST_PASSWORD` |

The Drive token is deliberately **not** in `homelab/volsync`. That secret is
copied into ~10 app namespaces, and the movers only need the REST login.

```bash
vault kv put secret/homelab/rclone-gdrive \
  CLIENT_ID='<client_id>' CLIENT_SECRET='<client_secret>' \
  TOKEN='<token JSON from rclone authorize>' \
  REST_USER=volsync REST_PASS="$(openssl rand -base64 32)"

# Copy the REST login to the movers' secret without printing it.
# If secret/homelab/volsync already exists, patch it:
vault kv patch secret/homelab/volsync \
  RESTIC_REST_USERNAME="$(vault kv get -field=REST_USER secret/homelab/rclone-gdrive)" \
  RESTIC_REST_PASSWORD="$(vault kv get -field=REST_PASS secret/homelab/rclone-gdrive)"

# Otherwise create it, including the restic encryption password:
vault kv put secret/homelab/volsync \
  RESTIC_PASSWORD="$(openssl rand -base64 32)" \
  RESTIC_REST_USERNAME="$(vault kv get -field=REST_USER secret/homelab/rclone-gdrive)" \
  RESTIC_REST_PASSWORD="$(vault kv get -field=REST_PASS secret/homelab/rclone-gdrive)"
```

**Keep a copy of `RESTIC_PASSWORD` outside the cluster** (password manager).
Without it every repository is unreadable, and Vault's own backup is one of
those repositories.

## Operations

```bash
# Gateway health
kubectl logs -n volsync-system deploy/rclone-restic

# Run one backup now
kubectl patch replicationsource backup-uptime-kuma -n monitoring --type merge \
  -p "{\"spec\":{\"trigger\":{\"manual\":\"$(date +%s)\"}}}"
kubectl get replicationsource backup-uptime-kuma -n monitoring \
  -o jsonpath='{.status.latestMoverStatus.result}{"\n"}'
```

- **Token revoked or expired** (log shows `invalid_grant`): run
  `rclone authorize` again, `vault kv patch secret/homelab/rclone-gdrive TOKEN='…'`.
  VSO restarts the gateway.
- **403 rate limit exceeded**: set `drive.tpsLimit: 8` in `values.yaml`.
- **Upload limit (750 GiB/day)**: the backup fails on purpose
  (`--drive-stop-on-upload-limit`) and continues on the next schedule.
- **Deleted data**: restic prune moves old packs to the Drive trash, which
  Google empties after 30 days. Don't empty it by hand: it's the undo window
  if the cluster ever deletes backups.
