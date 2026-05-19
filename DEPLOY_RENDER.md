# פריסה ל-Render — דשבורד ווב

## מה נוצר

שירות **Web** עם ממשק בעברית:

- **/** — לוח בקרה (הפעל/עצור בוט, Watch/Trade, סריקה)
- **/leaders** — רשימת סוחרים
- **/positions** — פוזיציות פתוחות וסגורות
- **/logs** — יומן אירועים

כתובת: `https://politrade-web.onrender.com` (או השם שבחרת)

## שלבים

1. [dashboard.render.com](https://dashboard.render.com) → **New → Blueprint**
2. Repo: `jdfrid/politrade`
3. **Apply**
4. ב-`politrade-web` → **Environment** הוסף:

| משתנה | ערך |
|--------|-----|
| `DASHBOARD_PASSWORD` | סיסמה לכניסה (משתמש: **admin**) |
| `PRIVATE_KEY` | מפתח פרטי (Secret) |
| `FUNDER_ADDRESS` | `0x088549349ff6deB90e60697012672A66743B1FFF` |
| `SIGNATURE_TYPE` | `1` |

5. **Save** → המתן ל-**Live**
6. פתח את ה-URL → התחבר: `admin` + הסיסמה

## שימוש

1. **סרוק מנהיגים** — כפתור בלוח או בדף מנהיגים
2. **התחל Watch** — סימולציה בלי כסף
3. **התחל Trade** — מסחר אמיתי (סכומים קטנים)
4. **עצור בוט** — עוצר את הלולאה
5. **Kill Switch** — חוסם הזמנות חדשות

## מקומי

```powershell
pip install -e .
set DASHBOARD_PASSWORD=yourpass
politrade-web
```

פתח: http://localhost:8000
