# Switch on real OTP login and automatic WhatsApp

Until these are set, the portal runs in **testing mode** (OTP shown on screen) and WhatsApp messages
use **one-tap send** (the teacher/office taps "Send on WhatsApp" on their own phone).

## 1. OTP by SMS (recommended first): Fast2SMS
1. Sign up at fast2sms.com with the school's mobile and email, and recharge (minimum Rs.100).
2. Complete **DLT registration** (Fast2SMS helps free): a sender ID (e.g. `SPVKTA`) and one
   transactional OTP template, for example:
   `Your SPV School login OTP is {#var#}. Valid for 5 minutes. Do not share it. - Sri Pragathi Vidyaniketan`
3. In Fast2SMS create a **Smart OTP** template using that DLT template. Note its **OTP ID**.
4. Copy the **API key** (Dev API).
5. Vercel → spvn → Settings → Environment Variables:
   - `FAST2SMS_API_KEY` = the API key (Sensitive)
   - `FAST2SMS_OTP_ID` = the OTP ID
   - `OTP_DEV_MODE` = `false`
6. Redeploy. Log in once with your own number to confirm the SMS arrives.

## 2. WhatsApp Business (automatic absent / fee / homework messages, OTP fallback)
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
   - `WA_TPL_OTP` = `login_otp`  (OTP goes by SMS first, WhatsApp if SMS fails;
     set `OTP_CHANNEL=whatsapp` to prefer WhatsApp)
5. Redeploy. Admin → Roles & data → System status shows "WhatsApp: Automatic".

Costs (check current rates): Meta charges per template message (utility and authentication rates for
India); Fast2SMS OTP from about Rs.0.11-0.25 per SMS depending on recharge.
