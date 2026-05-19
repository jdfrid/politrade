# פריסה ל-Render (מדריך בעברית)

## 1. GitHub (כבר מוכן)

Repo: **https://github.com/jdfrid/politrade**

## 2. יצירת שירות ב-Render

1. היכנס ל-[dashboard.render.com](https://dashboard.render.com)
2. **New +** → **Blueprint**
3. חבר את GitHub ובחר את `jdfrid/politrade`
4. Render יקרא את `render.yaml` ויצור **Background Worker** בשם `politrade`
5. לחץ **Apply**

## 3. משתני סביבה (חובה)

בשירות `politrade` → **Environment**:

| Key | Value | Secret? |
|-----|--------|---------|
| `PRIVATE_KEY` | `0x...` המפתח הפרטי **החדש** (לא זה ששיתפת בצ'אט) | כן |
| `FUNDER_ADDRESS` | `0x088549349ff6deB90e60697012672A66743B1FFF` | לא |
| `SIGNATURE_TYPE` | `1` (חשבון אימייל) | לא |
| `POLITRADE_MODE` | `watch` ואז `trade` | לא |
| `MAX_POSITION_USD` | `3`–`5` (יתרה ~$10) | לא |

אופציונלי: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

**Save Changes** → Render יעשה Deploy מחדש.

## 4. איך "רואים" את הבוט ב-Render

Worker **אין לו אתר** — רואים ב:

- **Dashboard** → `politrade` → **Logs** (פעילות בזמן אמת)
- **Events** (היסטוריית deploy)
- סטטוס **Live** = רץ

## 5. מעבר למסחר אמיתי

1. ודא שב-Logs של `watch` יש `copy_signal` / `dry_run_buy` בלי שגיאות
2. שנה `POLITRADE_MODE` ל-`trade`
3. עצירה: `KILL_SWITCH=1`

## 6. דיסק קבוע

`render.yaml` מגדיר דיסק ב-`/var/data` ל-SQLite ול-CLOB credentials.  
דורש תוכנית **Starter** ומעלה (לא Free בלבד).

## 7. עדכון קוד

כל `git push` ל-`main` מפעיל Deploy אוטומטי אם חיברת Auto-Deploy.
