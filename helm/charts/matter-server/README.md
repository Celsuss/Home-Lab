# Matter Server

The Matter controller for Home Assistant's **Matter** integration:
[matter.js Matter Server](https://github.com/matter-js/matterjs-server)
(`ghcr.io/matter-js/matterjs-server`). On HA OS this is the "Matter Server"
add-on. HA Container has no add-ons, so it runs here. The add-on builds from
the same image. Plan: `docs/plans/2026-10-20-apartment-dashboard.md`,
Phase 1a.

HA's Matter integration is only a client. This server holds the Matter
fabric, commissions devices and talks to them. Thread devices are reached
through the border router in `helm/charts/otbr`.

## Networking

- `hostNetwork: true`. Matter uses IPv6 link-local multicast and mDNS on the
  LAN (`primaryInterface: eno1`), and bridge networking doesn't work.
- The WebSocket API is **unauthenticated**, so it binds `127.0.0.1:5580`
  only. HA is also on the host network and connects over loopback. There's no
  Service or ingress on purpose. HA's Matter UI (Settings → Devices & services
  → Matter) covers what the server's own dashboard does.
- Host IPv6 prerequisites (forwarding for the border router, accepting router
  advertisements on `eno1`, NordVPN not disabling IPv6) are in Ansible:
  `ansible/roles/common/tasks/thread.yaml` and `20-ethernet.network.j2`.

## Storage: back this up

`/data` (`matter-server-pvc`) holds the fabric credentials and every
commissioned node. **If it's lost, every Matter device has to be
factory-reset and re-paired.** Add it to `volsync-backups` once that chart
covers the `home-assistant` namespace.

## Home Assistant setup (one-time, UI)

1. **Settings → Devices & services → Add integration → Matter**.
2. Uncheck "Use the official Matter Server Supervisor add-on" (there's no
   Supervisor) and enter the URL `ws://127.0.0.1:5580/ws`.
3. Pairing goes through the Companion app over Bluetooth. Thread devices also
   need the border router (`helm/charts/otbr` README) and the phone synced to
   HA's Thread credentials.

## Upgrades

Pinned in `values.yaml`. Follow what the HA add-on ships
(`home-assistant/addons` → `matter_server/build.yaml`, `build_from`). The
server migrates its storage on the first start of a new version, so
downgrades aren't safe without a backup.
