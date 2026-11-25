# SPV School Portal: database security

## What is in place now (free)
| Layer | How |
|---|---|
| Database | **Vercel Neon Postgres** (Vercel Storage → Neon, connected to the `spvn` project). No local or temporary storage in production: without the database the app refuses to run (fail closed). |
| Connection | TLS 1.2+ with the server certificate **and** host name verified. Unencrypted (`sslmode=disable`) connections to a remote database are refused. |
| Data at rest | Neon encrypts its disks. On top of that, the app encrypts **every record** with AES-256-GCM before it is sent to the database (`DATA_KEY`). Anyone who sees the database (a leaked connection string, the Neon console, a backup) sees only ciphertext. Each record is bound to its key, so records cannot be swapped or edited without detection. |
| Secrets | `DATABASE_URL` (from the Neon integration), `DATA_KEY`, `JWT_SECRET`, `VAN_KEY`, `CRON_SECRET` live only in Vercel environment variables. Nothing secret or personal is in the GitHub repo. |
| Who can reach data | Only the portal API, after mobile + OTP login. Roles are checked on the server for every request; parents only ever get their own children. The public status page shows only "ok". |
| Audit | Logins and every change are logged (`audit`). |

## Fee data and the admin
| Rule | How |
|---|---|
| Fee amounts and dashboards | Only the principal (and super admin) and the admin. Teachers and the correspondent never receive amounts from the server; a teacher sees only "fee reminder" (yes/no) and sends a reminder text without amounts. Parents see only their own children's fees. |
| Admin works only from the office | The admin role needs an **office device approved by the principal** (Roles & data > Admin office devices). A new phone or computer shows as "pending" until approved; the principal can remove it any time. |
| Optional: office internet only | `OFFICE_IPS` in Vercel (the office's public IP, e.g. `49.204.10.25`, or a range `49.204.10.0/24`). Ask the internet provider for a **static IP**; most home/office connections change IP. |
| Optional: office hours only | `OFFICE_HOURS` in Vercel, e.g. `08:00-18:00` (Monday-Saturday, IST). |

## The one limit of the free setup
A Neon database has a public internet address. It is protected by the password (only in Vercel), TLS and
the app encryption above, but anyone on the internet can still *try* to connect. Stopping that needs paid
networking:

| Option | What it does | Rough cost (check current prices) |
|---|---|---|
| **A. Free (now)** | Password + TLS + app-level encryption. Database address is public. | ₹0 |
| **B. IP allowlist** | Vercel **Static IPs** (Pro) + Neon **IP Allow** (Scale plan): the database accepts connections only from Vercel's fixed IPs. Traffic still crosses the internet, encrypted. | Vercel Pro + $100/month per project, plus a Neon Scale plan |
| **C. Fully private** | Vercel **PrivateLink** (Pro, needs Static IPs) + Neon **Private Networking** (AWS PrivateLink): the database is not reachable from the internet at all. | Option B costs + PrivateLink data transfer |

Recommendation for a school in Kota: **A now** (strong, free), and move to **B or C** if the school's
contract or rules require that the database is never reachable from the internet.

## Keep safe
- **`DATA_KEY` must never be lost.** If it is lost, the stored data cannot be read. Keep a copy offline
  (e.g. a password manager). Do not change it in Vercel: a new key cannot read existing data.
- Turn on two-factor login for the Vercel and GitHub accounts (whoever controls Vercel controls the data).
- Turn `OTP_DEV_MODE` off before real parents use the portal.

## Optional: least-privilege database user
The Neon integration connects as the database owner. To limit damage if the app were ever compromised,
create an app-only user in the Neon SQL editor and put its connection string in `DATABASE_URL`:
```sql
CREATE ROLE spv_app LOGIN PASSWORD '<long random password>';
GRANT CONNECT ON DATABASE neondb TO spv_app;
GRANT USAGE ON SCHEMA public TO spv_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON spv_kv TO spv_app;
```
(The table must already exist: open the portal once before switching.)
