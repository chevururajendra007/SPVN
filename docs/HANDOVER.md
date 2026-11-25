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

## Release 2 (25 Nov 2026)
- Super admin role (assigns roles from the portal), write-only admin, principal approval of fee entries
- Daily fee collection (approved payments only) on the dashboard and Fees tab
- Teacher "Fee reminder" button per student (once a day per child); absent message:
  "Dear parent, your kid: Name: <name> (Class N) is absent today. Kindly check and do the needful."
- Lesson scan: photos / PDF / text -> summary with key words (Telugu), memory tips and quiz; share to parents
  (AI: Vercel AI Gateway, google/gemini-2.5-flash; text-only fallback without AI)
- Practical sessions: 40-week plan per class band inspired by Japan and Europe, linked to Kota; mark done
- Real OTP and automatic WhatsApp: see `docs/SETUP_OTP_WHATSAPP.md`

## Rules
| Rule | Where |
|---|---|
| Fee reminder: balance > 30% of annual fee, at most once in 21 days | `school.fee_flag`, `school.reminder_due` |
| Absent alert: once per child per day, even if attendance is saved again | `school.save_attendance` |
| Class teacher can only see and mark their own class | `portal_api._class_for`, `skills.py` |
| Admin fee entry is pending until a principal/super admin approves; only approved money counts | `school.submit_fee_entry`, `decide_fee_entry` |
| Admin is write-only: no role changes, deletes, route edits, imports or attendance edits | `portal_api` permissions |
| Only a super admin assigns or removes roles | `portal_api.add_member/remove_member` |
| Fee amounts + dashboards only for principal/super admin/admin; teachers and correspondent get none | `portal_api.FEE_ROLES`, `school.card(fees=False)` |
| Admin works only on principal-approved office devices (+ optional OFFICE_IPS, OFFICE_HOURS) | `auth.office_check` |
| Parent sees only children whose record has their mobile number | `school.children`, `portal_api` |
| Test numbers starting with 5 are never messaged | `notify._valid` |

## Settings (Vercel → spvn → Settings → Environment Variables)
| Name | Purpose |
|---|---|
| `DATABASE_URL` | Vercel Neon Postgres (added by the Neon integration). **Required: the app will not run without it** |
| `DATA_KEY` | encrypts every stored record (AES-256-GCM). **Never lose or change it** (see SECURITY.md) |
| `JWT_SECRET` | signs login sessions (random, never share) |
| `OTP_DEV_MODE` | `true` shows the OTP on screen for testing. **Set to `false` before parents use it** |
| `SUPERADMIN_PHONES`, `PRINCIPAL_PHONES`, `CORRESPONDENT_PHONES`, `ADMIN_PHONES` | comma-separated numbers (a super admin can assign more in Roles & data) |
| `ADMIN_DEVICE_APPROVAL` | `true` (default): admin only on approved office devices |
| `ADMIN_PASSKEY`, `ADMIN_UNLOCK_HOURS` | `true`/12 (default): admin unlocks with fingerprint / Windows Hello on the approved device |
| `WA_LOGIN_NUMBER`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` | free "Verify on WhatsApp" login (see SETUP_OTP_WHATSAPP.md) |
| `OFFICE_IPS`, `OFFICE_HOURS` | optional: admin only from the office IP / in office hours |
| `WA_TPL_OTP`, `OTP_CHANNEL` | login OTP on WhatsApp (default `whatsapp`; `sms`/`both` with `FAST2SMS_API_KEY`, `FAST2SMS_OTP_ID`) |
| `WA_TPL_DEFAULT` | WhatsApp utility template used for all school messages |
| `AI_GATEWAY_API_KEY` (optional), `LESSON_MODEL` | lesson scan AI; without a key the Vercel OIDC token is used |
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
- [x] Vercel Neon Postgres only, TLS verified, every record encrypted in the app (`docs/SECURITY.md`)

## Runbook
| Problem | Check | Fix |
|---|---|---|
| "Database not connected" | Team & data → System status | Check the Neon integration on the project and `DATA_KEY`; redeploy |
| Parent says "number not registered" | Search the child; check the parent mobile | Fix the number in Excel and re-import |
| WhatsApp not arriving | WhatsApp tab: status `failed`/`queued` | Check token/templates; meanwhile use one-tap send |
| Van not moving on map | Bus routes: "No GPS yet"/"Offline" | Phone: Traccar service on, location "Allow all the time", battery saver off |
| Fee reminders did not go | Fees tab → "Last run" | Vercel → Cron Jobs; press "Send due reminders now" |
| Need to roll back | Vercel → Deployments | Promote the previous deployment |

## Test
`SPV_SEED=<seed.json> python -m pytest tests -q` (portal + security tests; add `DATABASE_URL` and `SECURITY_PG` to run them on Postgres).
