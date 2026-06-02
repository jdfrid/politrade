"""User-facing CLOB / Polymarket API error messages."""

from __future__ import annotations


def classify_clob_error(exc: Exception) -> tuple[str, str]:
    """Return (reason_code, hebrew_message) for display in the UI."""
    text = str(exc).lower()

    if "restricted in your region" in text or "geoblock" in text:
        return (
            "geoblock",
            "Polymarket חוסם מסחר מהאזור של השרת (Render בארה״ב). "
            "הרץ את הבוט מהמחשב שלך, או העבר ל-VPS באירופה/אזור מותר.",
        )
    if "maker address not allowed" in text or "deposit wallet flow" in text:
        return (
            "deposit_wallet",
            "Polymarket דורש Deposit Wallet (Signature Type 3). "
            "העתק Deposit Address מהגדרות Polymarket, בחר סוג 3, ולחץ 'אפס מפתח API'. "
            "מומלץ לבצע עסקה אחת ידנית באתר Polymarket לפני הבוט.",
        )
    if "order owner has to be the owner" in text or "signer address has to be" in text:
        return (
            "api_key_mismatch",
            "מפתח API לא תואם לארנק — לחץ 'אפס מפתח API' בדף הארנק ושמור מחדש.",
        )
        return "insufficient_balance", "יתרה לא מספקת בארנק Polymarket."
    if "invalid signature" in text or "signature" in text and "invalid" in text:
        return "bad_signature", "חתימה לא תקינה — בדוק Private Key ו-Signature Type (1 לחשבון Email)."
    if "unauthorized" in text or "401" in text:
        return "unauthorized", "אימות נכשל — בדוק Private Key, Funder ו-Signature Type."
    if "market" in text and ("closed" in text or "inactive" in text):
        return "market_closed", "השוק סגור או לא פעיל — לא ניתן לסחור."
    if "rate limit" in text or "429" in text:
        return "rate_limit", "יותר מדי בקשות — נסה שוב בעוד דקה."

    short = str(exc).strip()
    if len(short) > 180:
        short = short[:177] + "…"
    return "unknown", f"שגיאת מסחר: {short}"


def format_clob_error(exc: Exception) -> str:
    return classify_clob_error(exc)[1]


RISK_REASONS_HE: dict[str, str] = {
    "kill_switch_active": "Kill Switch פעיל — בטל בלוח הבקרה.",
    "position_too_small": "סכום העסקה קטן מדי.",
    "max_open_positions": "הגעת למקסימום פוזיציות פתוחות.",
    "max_total_exposure": "הגעת למקסימום חשיפה כוללת.",
    "insufficient_balance": "יתרה לא מספקת בארנק.",
}


def format_risk_reason(code: str) -> str:
    return RISK_REASONS_HE.get(code, f"נדחה: {code}")
