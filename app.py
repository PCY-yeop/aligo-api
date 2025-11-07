# app.py (FastAPI 예시)
import os, re, json
from datetime import datetime
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

ALIGO_USER_ID = os.getenv("ALIGO_USER_ID", "")
ALIGO_KEY     = os.getenv("ALIGO_KEY", "")
ALIGO_SENDER  = re.sub(r"[^\d]", "", os.getenv("ALIGO_SENDER", ""))
SERVICE_NAME  = os.getenv("SERVICE_NAME", "")

if not (ALIGO_USER_ID and ALIGO_KEY and ALIGO_SENDER):
    raise RuntimeError("ENV 누락: ALIGO_USER_ID / ALIGO_KEY / ALIGO_SENDER")

DIGITS = re.compile(r"[^\d]")
def only_digits(s): return DIGITS.sub("", s or "")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

@app.get("/health")
async def health():
    return {"ok": True, "time": datetime.now().isoformat()}

def build_text(site, vd, vt_label, name, phone):
    site_disp = site or SERVICE_NAME or "-"
    if site_disp and not (site_disp.startswith("[") and site_disp.endswith("]")):
        site_disp = f"[{site_disp}]"
    lines = [
        f"현장 : {site_disp}",
        f"날짜 : {vd or '-'}",
        f"시간 : {(vt_label or '-').strip()}",
        f"이름 : {name or '-'}",
        f"연락처 : {phone or '-'}",
    ]
    return "\n".join(lines)

@app.post("/sms")
async def send_sms(req: Request):
    """
    요청 JSON 예:
    {
      "site":"보라매", "vd":"2025-11-07",
      "vtLabel":"10:00 ~ 11:00",
      "name":"홍길동", "phone":"010-1234-5678",
      "sp":"01022844859"               // 수신자(관리자) 번호
    }
    """
    data = await req.json()
    site     = (data.get("site") or "").strip()
    vd       = (data.get("vd") or "").strip()
    vt_label = (data.get("vtLabel") or "").strip()
    name     = (data.get("name") or "").strip()
    phone    = only_digits(data.get("phone"))
    admin_sp = only_digits(data.get("sp") or "")

    if not admin_sp:
        return {"ok": False, "error": "수신자(sp) 번호 누락"}
    if not (ALIGO_USER_ID and ALIGO_KEY and ALIGO_SENDER):
        return {"ok": False, "error": "서버 환경변수 누락"}

    text = build_text(site, vd, vt_label, name, phone)

    # 알리고 전송: https://apis.aligo.in/send/
    # 필수: user_id, key, sender, receiver, msg
    payload = {
        "user_id": ALIGO_USER_ID,
        "key": ALIGO_KEY,
        "sender": ALIGO_SENDER,
        "receiver": admin_sp,     # 수신자 번호(숫자만)
        "msg": text,
        # 선택 파라미터 예시:
        # "title": "[알림]",          # LMS일 때 제목
        # "msg_type": "SMS",         # 기본은 자동판별, 강제 가능
        # "testmode_yn": "Y",        # 테스트모드(Y)면 실제 과금 없음
    }
    # --- 알리고 호출 ---
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post("https://apis.aligo.in/send/", data=payload)
        try:
            res = r.json()
        except Exception:
            res = {"raw": r.text}

    # --- 응답 정리 ---
    result_code = str(res.get("result_code", ""))
    ok = (result_code == "1")
    return {
        "ok": ok,
        "code": result_code,
        "message": res.get("message"),
        "aligo": res,
        "to": admin_sp,
        "from": ALIGO_SENDER,
        "preview": text,
    }
