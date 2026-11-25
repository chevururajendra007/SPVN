# Login without paying for OTPs

## How parents log in (free)
1. Open the portal, type the mobile number, tap **Verify on WhatsApp (free)**.
2. WhatsApp opens with a ready message `LOGIN SPV 123456` to the school's **portal WhatsApp number**. Tap **Send**.
3. Go back to the portal: logged in. The phone stays logged in for **1 year**.

Free because messages that parents send to a business number cost nothing, and our "Verified" reply
is inside the free 24-hour window. Secure because WhatsApp already verified the sender's number, Meta
signs every webhook, and the code works once, for 10 minutes, only from the typed mobile number.

## One-time setup (school / Rajendra)
The school's existing **normal WhatsApp stays as it is**. The portal needs its own number on the free
WhatsApp Cloud API (Meta charges nothing for receiving messages or for free replies).

1. Buy a new prepaid SIM for the portal (any operator). It only needs to receive one SMS/call for
   verification. Do NOT install WhatsApp on it.
2. Go to business.facebook.com, create a Business portfolio for "Sri Pragathi Vidyaniketan".
3. Go to developers.facebook.com, **Create app** > type **Business** > add the **WhatsApp** product.
4. WhatsApp > API Setup > **Add phone number**: enter the new SIM's number, display name
   "SPV School Portal", verify with the code.
5. Note the **Phone number ID**.
6. Business settings > Users > System users > add a system user (Admin), **Generate token** for this app
   with `whatsapp_business_messaging` and `whatsapp_business_management`, never-expiring. Copy the token.
7. App settings > Basic > copy the **App secret**.
8. WhatsApp > Configuration > Webhook:
   - Callback URL: `https://spvn.vercel.app/api/whatsapp/webhook`
   - Verify token: any long random word you choose (e.g. `spv-webhook-7Kq2...`)
   - Click Verify and save, then **Subscribe** to the `messages` field.
   (Add the Vercel variables in step 9 **before** clicking Verify.)
9. Vercel > spvn > Settings > Environment Variables (Sensitive), then Redeploy:
   - `WA_LOGIN_NUMBER` = the portal number with 91, e.g. `919876543210`
   - `WHATSAPP_TOKEN` = token from step 6
   - `WHATSAPP_PHONE_ID` = phone number ID from step 5
   - `WHATSAPP_APP_SECRET` = app secret from step 7
   - `WHATSAPP_VERIFY_TOKEN` = the verify token from step 8
   - `OTP_DEV_MODE` = `false` (removes the on-screen testing code)
10. Test: log in with your own number using "Verify on WhatsApp".

Tip: keep the app in "Development" mode only for tests with up to 5 numbers; publish the app (Live) and
complete Business verification for all parents.

## Paid messages (optional)
Absent / fee / homework alerts sent by the school to a parent who has not messaged in 24 hours need an
approved template and cost about Rs.0.115 + GST each. Until then teachers send them free with one tap
from their own WhatsApp (current setup). Template setup: create a Utility template `school_notice`
with body `Sri Pragathi Vidyaniketan, Kota: {{1}}` and set `WA_TPL_DEFAULT=school_notice`.
Paid OTP by WhatsApp template (`WA_TPL_OTP`) or SMS (`OTP_CHANNEL=sms`, Fast2SMS) stays available but is
not needed.
