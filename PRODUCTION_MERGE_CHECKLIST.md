# Production Merge Checklist — dev → main

Runbook for updating production (`main`) without losing data.
Status right now: **initial backup taken ✓ — persistent volume NOT yet added,
live matches in progress → do the steps below only after they finish.**

> Background: production currently stores its SQLite database *inside* the
> container, so **every redeploy wipes it** — including the redeploy that
> adding a volume triggers. That's why the order below matters.

## 1. Wait until no matches are being tracked

Everything below causes a short downtime and a container replacement.

## 2. Final backup (SSH into the VPS)

Find the container (either method):

```bash
# A: Coolify → tennis app → Terminal → run `hostname` → that IS the container ID
# B: on the VPS:
docker ps --no-trunc --format '{{.ID}}  {{.Names}}  {{.Command}}' | grep uvicorn
```

Confirm and copy the database out:

```bash
docker exec <id> ls -la /app/data          # tennis.db should be there
docker cp <id>:/app/data/tennis.db ~/tennis-prod-backup.db
```

## 3. Add the persistent volume in Coolify

Production app → **Storages → + Add → Volume Mount**
- Destination: **`/app/data`** (must be exact)
- Save → **Redeploy** (the app starts with an empty DB in the new volume — expected)

## 4. Restore the data into the volume

```bash
docker ps --no-trunc --format '{{.ID}}  {{.Names}}  {{.Command}}' | grep uvicorn   # NEW id
docker cp ~/tennis-prod-backup.db <new-id>:/app/data/tennis.db
```

Then **Restart** the app in Coolify and check the site shows the old match days.

## 5. Set production environment variables (Coolify → app → Environment)

- `ADMIN_EMAIL` = your admin login email
- `ADMIN_PASSWORD` = your admin password

(Old main only used `ADMIN_PASSWORD`; the new code syncs the superadmin
account from both vars on every boot — also works as a password reset.)

## 6. Merge dev → main

```bash
git checkout main && git pull origin main
git merge dev
git push origin main
```

Coolify rebuilds and deploys main. First build is slower (~5–10 min, Flutter
builder image); later builds are cached.

## 7. Verify after the deploy

- Deploy log shows `Database backed up to /app/data/tennis.backup-…` and
  `Superadmin created/updated: …`
- Old match days visible in the archive, scores intact
- Login works at `/admin/login` with the env credentials
- Flutter web app loads at `/app`

## If something goes wrong

The app snapshots the DB **on every startup before migrations** (newest 5 kept,
inside the volume). Restore any of them:

```bash
docker exec <id> ls /app/data                    # list backups
docker cp ~/tennis-prod-backup.db <id>:/app/data/tennis.db   # or use a tennis.backup-*.db
# then Restart the app in Coolify
```

Rolling back the code = revert the merge commit on main and push; the data
stays in the volume either way.

---

Notes verified in advance (2026-07-12):
- Booting the new code on a database created by current main preserved all
  match days/matches and mid-game scores; ownerless match days are backfilled
  to the superadmin; old scorer tokens keep working.
- Schema migrations are additive only (new tables/columns, no drops).
