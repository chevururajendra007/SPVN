# SPV School Portal: handover

## Problem brief
Parents in Kota hear about absence, fees and homework late (paper diary, phone calls). The principal has no
same-day view of attendance or fee collection, and parents cannot see where the school van is.

**Success metric:** share of absent students whose parent is told the same morning.
Baseline: unknown (record it in the pilot's first week). Target: 100% within 30 minutes of the roll call, by the end of the pilot.
Secondary: fee collection % at the end of term against last term.

## MVP (this release)
1. Login for parents, class teachers, principal, correspondent and admin, with mobile number + OTP
2. Class teacher marks P/A → parent of each absent child gets WhatsApp
3. Parent dashboard: attendance, marks, fees + reminder, homework, updates, van
4. Principal dashboards: attendance by class, fees by class, list of students above 30% pending, search
5. Fee reminder every 3 weeks when more than 30% is unpaid (daily job at 09:00 IST)
6. Homework → parents · circulars → staff · admin updates → parents
7. Bus routes with live van location from the Traccar Client phone app
8. Ask SPV agent with role-limited, read-only skills

**Out of scope (for now):** online fee payment, marks entry screen (marks come from Excel), timetable,
report cards/PDFs, push notifications, student logins, SMS OTP (WhatsApp/testing only), Telugu UI translation.

## Rules
| Rule | Where |
|---|---|
| Fee reminder: balance > 30% of annual fee, at most once in 21 days | `school.fee_flag`, `school.reminder_due` |
| Absent alert: once per child per day, even if attendance is saved again | `school.save_attendance` |
| Class teacher can only see and mark their own class | `portal_api._class_for`, `skills.py` |
| Parent sees only children whose record has their mobile number | `school.children`, `portal_api` |
| Test numbers starting with 5 are never messaged | `notify._valid` |

## Settings (Vercel → spvn → Settings → Environment Variables)
| Name | Purpose |
|---|---|
| `DATABASE_URL` | Neon Postgres. **Required before real use.** Added by connecting Neon (Storage tab) |
| `JWT_SECRET` | signs login sessions (random, never share) |
| `OTP_DEV_MODE` | `true` shows the OTP on screen for testing. **Set to `false` before parents use it** |
| `PRINCIPAL_PHONES`, `CORRESPONDENT_PHONES`, `ADMIN_PHONES` | comma-separated numbers (more can be added in Team & data) |
| `VAN_KEY` | secret in the van phones' server URL |
| `CRON_SECRET` | protects the daily fee-reminder job |
| `SEED_DATA` | test data (gzip + base64 of the seed JSON); remove once real data is imported |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID` | WhatsApp Business Cloud API for automatic sending |
| `WA_TPL_ABSENT`, `WA_TPL_FEE`, `WA_TPL_HOMEWORK`, `WA_TPL_UPDATE`, `WA_TPL_CIRCULAR`, `WA_TPL_OTP` | approved template names (one `{{1}}` variable; OTP = authentication template) |

## Security checklist
- [x] Roles are checked on the server for every request, never trusted from the app
- [x] Agent skills are read-only; identity is bound on the server (prompt injection cannot reach other families)
- [x] OTP: hashed, 5 minutes, 5 tries, 30 s resend gap
- [x] No personal data in the public GitHub repo
- [x] Audit log of logins and every change (`audit` key)
- [ ] Turn off `OTP_DEV_MODE` and connect WhatsApp OTP before real parents log in
- [ ] Connect Neon Postgres (until then data is not saved reliably)

## Runbook
| Problem | Check | Fix |
|---|---|---|
| Red "database is not connected" banner | Team & data → System status | Connect Neon to the project, redeploy |
| Parent says "number not registered" | Search the child; check the parent mobile | Fix the number in Excel and re-import |
| WhatsApp not arriving | WhatsApp tab: status `failed`/`queued` | Check token/templates; meanwhile use one-tap send |
| Van not moving on map | Bus routes: "No GPS yet"/"Offline" | Phone: Traccar service on, location "Allow all the time", battery saver off |
| Fee reminders did not go | Fees tab → "Last run" | Vercel → Cron Jobs; press "Send due reminders now" |
| Need to roll back | Vercel → Deployments | Promote the previous deployment |

## Test
`SPV_SEED=<seed.json> python -m pytest tests -q` (17 tests; add `DATABASE_URL` to run them on Postgres).
