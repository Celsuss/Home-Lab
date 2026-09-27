# second-brain

Syncs the org-roam second brain (`celsuss/second-brain`) into an Open WebUI knowledge base,
so chats can retrieve from your own notes instead of only the web.

**Read-only.** Nothing in this chart writes back to git. The clone is reset to the remote on
every run.

## How it works

```
GitHub ──mirror──► Forgejo celsuss/second-brain (private)
                     │  read-only token, in-cluster
                     ▼
               second-brain-pvc ──► sync CronJob (hourly, :17)
                                      │  manifest {path, filename, sha256, size}
                                      ▼
                                    Open WebUI  POST /api/v1/knowledge/{id}/sync/diff
                                      │  upload added+modified, cleanup deleted
                                      ▼
                                    knowledge base "Second Brain"
```

Open WebUI 0.11.4 ships a purpose-built incremental sync API, so **the diffing happens
server side**: `sync.py` sends a manifest of every note with its SHA-256, and Open WebUI
answers with `added / modified / deleted / mkdir / rmdir / unmodified_count`. Unmodified
notes cost nothing, which is what makes an hourly schedule reasonable for 1,680 files.

The clone source is **Forgejo, not GitHub**, for two reasons: this pod then needs no
internet egress at all, and the URL stays correct when Forgejo stops being a pull mirror
and becomes the writable origin.

### What `sync.py` does to each note

1. **Rewrites roam id-links.** `[[id:<uuid>][Beta]]` → `[[Beta]]`, and a bare
   `[[id:<uuid>]]` → `[[<that note's title>]]`. This is the highest-value step in the
   whole chart: a retrieved chunk full of raw UUIDs tells a model nothing, while titles
   give it something to ask for next. Unresolvable ids become `[[unknown note]]`.
2. **Prepends an identity preamble** (`Note:`, `Also known as:`, `Tags:`, `Source:`) so the
   *first* chunk of every note carries its own name — that is what the vector search
   matches against.
3. **Hashes the transformed bytes**, not the bytes on disk. Getting this backwards makes
   every run re-upload the entire corpus, because the stored `file_hash` is of what was
   uploaded.

Skipped: `ltximg/`, Emacs backups (`*.org~`), auto-saves (`.#*.org`), and everything
outside `org-roam/` (`hugo/`, `images/`, `stats/`).

### Why the upload is one call per note

`POST /api/v1/files/` with `knowledge_id` in the metadata makes Open WebUI extract, embed
**and** link the file into the knowledge base in a single request
(`routers/files.py:227-252`), which saves a second `files/batch/add` round-trip.
`process_in_background=false` makes it synchronous, so slow embeddings apply backpressure
here rather than piling up inside the Open WebUI pod.

Each note is embedded twice — once into its own `file-<id>` collection, once into the
knowledge base collection. That is unavoidable through the public API; `batch/add` does
exactly the same thing. Measured cost: **0.27 s/note**, so the ~1,680-note first run takes
about 8 minutes. Steady-state runs finish in seconds.

## Manual steps

### 1. Vault secret (before first sync)

A Forgejo access token with **`read:repository` scope only**, minted at
<https://forgejo.homelab.local/user/settings/applications>. It is needed because
`celsuss/second-brain` is private in Forgejo, unlike the other three mirrors.

```bash
vault kv put secret/homelab/second-brain \
  forgejo-user="celsuss" \
  forgejo-token="<token>"
```

The Open WebUI admin key is **not** new — this chart reads the existing
`secret/homelab/open-webui` `admin-api-key`, shared with the `cptr` and `open-terminal`
hooks. Check it still works before deploying:

```bash
vault kv get -field=admin-api-key secret/homelab/open-webui
```

### 2. Use the knowledge base

Attach it under Workspace → Models → *model* → Knowledge, or reference it in a chat with
`#`.

**Set the model to Native function calling.** On Native, the model gets
`query_knowledge_files` and searches the brain agentically. On Legacy it instead gets a
blind top-K injection — with `TOP_K: 3` against 1,680 atomic notes, that is a thin and
often irrelevant three paragraphs. See `helm/charts/open-webui/README.md` for the
Native/Legacy trap in general.

## Freshness

The knowledge base trails your laptop by two hops:

| Hop | Latency | Fixed by |
|---|---|---|
| laptop → GitHub | manual `git push` (historically ~weekly) | only you |
| GitHub → Forgejo | the mirror interval (the other three mirrors are `8h`) | shorten it in Forgejo's repo settings |
| Forgejo → knowledge base | ≤ 1 hour | `schedule` in `values.yaml` |

Worth checking `second-brain`'s mirror interval and dropping it to ~1h — otherwise a note
written today can take most of a day to become searchable.

## Retrieval tuning (not done by this chart)

The live Open WebUI settings are still the stock defaults, which suit a handful of PDFs
rather than 1,680 short notes:

| Setting | Now | Suggested | Why |
|---|---|---|---|
| `TOP_K` | 3 | 6 | org-roam notes are atomic; three is a thin answer |
| `ENABLE_RAG_HYBRID_SEARCH` | false | true | a personal wiki is dense with proper nouns and package names that BM25 nails and embeddings blur |
| `RAG_EMBEDDING_BATCH_SIZE` | 1 | 32 | only matters for the first bulk ingest |
| `RAG_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` (CPU) | an Ollama GPU model | MiniLM truncates at 256 tokens, clipping a 1000-char chunk |

These are **PersistentConfig** — the database copy wins over env vars after first boot, so
setting them in `open-webui`'s `values.yaml` would look correct and do nothing. Change them
in the admin UI, or add a PostSync hook here on the `open-terminal` configure-job pattern.

**Changing the embedding model invalidates the index** and requires
`POST /api/v1/knowledge/reindex` plus a full re-embed.

## Storage

One 1Gi RWO PVC on `local-path` holding a shallow clone (~38 MB). The script expires the
reflog and runs `git gc` after each fetch, or shallow fetches accumulate a pack per run.

**Not backed up, deliberately.** It is a disposable copy of a remote repo — restoring it
costs one `git clone`. Do not add it to `helm/charts/volsync-backups/values.yaml`.

## Containment

This pod reads a private notes repo and holds an Open WebUI admin key, so the
NetworkPolicy allows exactly three destinations: cluster DNS, `forgejo-http.forgejo:3000`,
and `open-webui:8080`. There is **no internet egress rule** and no ingress rule — nothing
ever connects *to* a CronJob. `automountServiceAccountToken: false`, so it has no
Kubernetes credentials.

The Forgejo rule selects the **backend pod and its container port**, not the Service VIP:
an `ipBlock` naming a Service or LoadBalancer VIP never matches, because the VIP is DNAT'd
to the pod IP before the policy is evaluated.

### Verifying the NetworkPolicy

A NetworkPolicy is silently inert if the controller is off, so check it rather than
assuming. **k3s enforces with kube-router, whose default action is `REJECT`, not `DROP`** —
a blocked connection comes back as an *instant* `curl: (7) ... after 0 ms`, never a hang.
Expecting a timeout will make a working policy look broken.

```bash
kubectl -n ai-workloads run np-check --rm -it --restart=Never \
  --labels=app=second-brain --image=curlimages/curl -- sh -c '
    curl -m 3 -o /dev/null -w "forgejo %{http_code}\n" http://forgejo-http.forgejo.svc.cluster.local:3000/
    curl -m 3 -o /dev/null -w "owui    %{http_code}\n" http://open-webui.ai-workloads.svc.cluster.local:8080/health
    curl -m 3 https://github.com    # must fail instantly - no internet egress
    curl -m 3 http://192.168.0.1    # must fail instantly - the LAN is unreachable
  '
```

Do not test against the node's own IP (`192.168.0.142`): pod-to-own-node traffic is a
NetworkPolicy blind spot that CNIs commonly exempt, so it proves nothing either way.

## Running it by hand

`sync.py` is stdlib-only and takes everything from the environment, so it runs fine against
a local checkout — this is the fastest way to test a change before committing:

```bash
KB_NAME="Second Brain (dry run)" \
OPEN_WEBUI_URL="https://open-webui.homelab.local" \
OPEN_WEBUI_API_KEY="$(vault kv get -field=admin-api-key secret/homelab/open-webui)" \
REPO_DIR="$HOME/workspace/second-brain" \
INSECURE_TLS=1 \
  python3 helm/charts/second-brain/files/sync.py --dry-run
```

`--dry-run` reports the diff and changes nothing (and will not create the knowledge base).
`--limit N` restricts the run to the first N notes. `INSECURE_TLS=1` is only needed off
-cluster, because `open-webui.homelab.local` uses the homelab CA.

Force a run in-cluster:

```bash
kubectl -n ai-workloads create job --from=cronjob/second-brain-sync sync-now
kubectl -n ai-workloads logs -f job/sync-now
```

The run is idempotent, so a second one immediately after should report
`added=0 modified=0 deleted=0` — that is the single best check that everything is wired up.

## Notes

- **Deleting a knowledge base orphans its files.** `DELETE /api/v1/knowledge/{id}/delete`
  leaves every underlying file behind in `/api/v1/files/`. If you ever delete and recreate
  the knowledge base, clean those up too or they accumulate silently.
- The `files` listing endpoint does not project a file's `directory_id`; it lives in
  `meta.data.directory_id`. A file can look unfiled there while the server's own
  `sync/diff` correctly places it.
- Writing notes from Open WebUI is deliberately not implemented. It would fit as a sibling
  Deployment mounting the same PVC and registering an OpenAPI tool server via
  `POST /api/v1/configs/tool_servers` — but it first needs Forgejo to stop being a pull
  mirror, because a mirror cannot be pushed to.
