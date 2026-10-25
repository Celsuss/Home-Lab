# Tasks

## RomM

- [ ] Add metadata provider API keys to Vault with `vault kv patch secret/homelab/romm` (not `put`), then check that a rescan picks up the new artwork and metadata. See `helm/charts/romm/README.md`.
  - [ ] ScreenScraper: `SCREENSCRAPER_USER`, `SCREENSCRAPER_PASSWORD` (https://www.screenscraper.fr)
  - [ ] RetroAchievements: `RETROACHIEVEMENTS_API_KEY` (https://retroachievements.org/settings)
  - [ ] SteamGridDB: `STEAMGRIDDB_API_KEY` (https://www.steamgriddb.com/profile/preferences/api)
  - [ ] IGDB: `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET` (Twitch app at https://dev.twitch.tv/console/apps)

## Cluster

- [ ] Raise the node's pod limit. K3s caps a node at 110 pods by default, and the single node is at that limit. On 2026-10-25, VolSync's first backup round (about 23 backup pods at once) left `vault-data`, `kanidm-data` and `khoj-postgres` Pending with `0/1 nodes are available: 1 Too many pods`. While the node is full, any app pod that restarts can't be scheduled either.
  - [ ] Add `kubelet-arg: ["max-pods=200"]` to `ansible/roles/k3s/templates/config.yaml.j2`. That file already has uncommitted local changes; review them first.
  - [ ] Apply with `ansible-playbook ansible/playbooks/site.yaml`, which restarts K3s. Run `ansible-playbook --check ansible/playbooks/site.yaml` first. `site.yaml` has no tags, so `--tags k3s` would run nothing.
  - [ ] Check that the node reports `pods: 200` under capacity (`kubectl get node archlinux -o jsonpath='{.status.capacity.pods}'`) and that no pods are stuck Pending.

## Backups (VolSync → Google Drive)

- [ ] After the first backup round finishes, check that every ReplicationSource reports `Successful` (`kubectl get replicationsource -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,RESULT:.status.latestMoverStatus.result`). Large volumes may fail on Drive's 750 GiB/day upload limit and complete over the following nights.
- [ ] Phase 3 restore test: restore `uptime-kuma` into a scratch PVC with a `ReplicationDestination` and check the files. See `docs/plans/2026-10-25-volsync-google-drive.md`.
- [ ] Save `RESTIC_PASSWORD` from `secret/homelab/volsync` in the password manager. Without it, no backup can be restored.
