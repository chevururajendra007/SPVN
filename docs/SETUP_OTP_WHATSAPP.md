# Switch on real OTP login and automatic WhatsApp

Until these are set, the portal runs in **testing mode** (OTP shown on screen) and WhatsApp messages
use **one-tap send** (the teacher/office taps "Send on WhatsApp" on their own phone).

## 1. WhatsApp Business: login OTP and all school messages (default)
1. Create a Meta Business account and a WhatsApp Business **Cloud API** app (developers.facebook.com).
   Use a mobile number that is not already on the WhatsApp app (e.g. a new school SIM).
2. Create these message templates (language English) and wait for approval:
   - `school_notice` - category **Utility**, body:
     `Sri Pragathi Vidyaniketan, Kota: {{1}}`
     (the app puts the full absent / fee / homework / update text into {{1}})
   - `login_otp` - category **Authentication** (Meta's fixed OTP text with a copy-code button)
3. Create a permanent System User token with `whatsapp_business_messaging` permission.
4. Vercel environment variables:
   - `WHATSAPP_TOKEN` (Sensitive), `WHATSAPP_PHONE_ID` (the phone number ID, not the number)
   - `WA_TPL_DEFAULT` = `school_notice`
   - `WA_TPL_OTP` = `login_otp`  (login OTP goes on WhatsApp only)
   - `OTP_DEV_MODE` = `false`
5. Redeploy. Admin → Roles & data → System status shows "WhatsApp: Automatic".

## 2. Optional: SMS OTP instead (Fast2SMS)
Only if some parents do not use WhatsApp. Set `OTP_CHANNEL=both` (WhatsApp first, then SMS) or `sms`.

1. Sign up at fast2sms.com with the school's mobile and email, and recharge (minimum Rs.100).
2. Complete **DLT registration** (Fast2SMS helps free): a sender ID (e.g. `SPVKTA`) and one
   transactional OTP template, for example:
   `Your SPV School login OTP is {#var#}. Valid for 5 minutes. Do not share it. - Sri Pragathi Vidyaniketan`
3. In Fast2SMS create a **Smart OTP** template using that DLT template. Note its **OTP ID**.
4. Copy the **API key** (Dev API).
5. Vercel → spvn → Settings → Environment Variables:
   - `FAST2SMS_API_KEY` = the API key (Sensitive)
   - `FAST2SMS_OTP_ID` = the OTP ID
6. Redeploy. Log in once with your own number to confirm the SMS arrives.


Costs (check current rates): WhatsApp India about Rs.0.115 per authentication or utility template + 18% GST.
Free on WhatsApp: any message sent within 24 hours after the parent last messaged the school number, and
non-template replies in that window. A parent logs in about once in 90 days (session length), so login OTP
costs roughly Rs.0.14 per parent per quarter. Fast2SMS OTP is about Rs.0.11-0.25 per SMS.
