# app.py (ALIGO - 고정 발신번호 전용)
# - 무조건 등록된 기본 발신번호(ALIGO_SENDER)로만 발송
# - sp(수신자)는 to 로만 사용, from 은 항상 ENV_SENDER
# - 실패 원인은 잔액/점검/차단 외엔 거의 사라짐

import os, re, json
from datetime import datetime
import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# ========= ENV =========
ALIGO_API_KEY = os.getenv("ALIGO_API_KEY", "")
ALIGO_USER_ID = os.getenv("ALIGO_USER_ID", "")
ENV_SENDER    = os.getenv("ALIGO_SENDER", "")  # 반드시 알리고에 등록/승인된 발신번호

if not (ALIGO_API_KEY and ALIGO_USER_ID and ENV_SENDER):
    raise RuntimeError("ENV 누락: ALIGO_API_KEY / ALIGO_USER_ID / ALIGO_SENDER")

# ========= APP / CORS =========
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 운영 시 허용 도메인으로 제한 권장
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========= UTILS =========
DIGITS = re.compile(r"[^\d]")

def only_digits(s: str) -> str:
    return DIGITS.sub("", s or "")

def build_admin_text(site: str, vd: str, vt_label: str, name: str, phone: str, memo: str) -> str:
    """관리자에게 보낼 본문(요청한 5줄 포맷)"""
    site_disp = site or ""
    if site_disp and not (site_disp.startswith("[") and site_disp.endswith("]")):
        site_disp = f"[{site_disp}]"
    time_disp = (vt_label or "").strip() or "-"
    lines = [
        f"현장 : {site_disp or '-'}",
        f"날짜 : {vd or '-'}",
        f"시간 : {time_disp}",
        f"이름 : {name or '-'}",
        f"연락처 : {phone or '-'}",
    ]
    # 필요 시 메모 추가
    # if memo: lines.append(f"메모 : {memo}")
    return "\n".join(lines)

def need_lms(text: str) -> bool:
    """
    길이 기준으로 LMS 제목 포함 여부 결정.
    (보수적으로 UTF-8 90바이트 초과 시 LMS 제목 추가)
    """
    try:
        return len(text.encode("utf-8")) > 90
    except Exception:
        return True

ALIGO_SEND_URL = "https://apis.aligo.in/send/"

def aligo_send(sender: str, receiver: str, msg: str, title: str = "") -> dict:
    data = {
        "key": ALIGO_API_KEY,
        "user_id": ALIGO_USER_ID,
        "sender": sender,
        "receiver": receiver,
        "msg": msg,
    }
    if title:
        data["title"] = title
    try:
        r = requests.post(ALIGO_SEND_URL, data=data, timeout=15)
        try:
            return r.json()
        except Exception:
            return {"result_code": "parse_error", "raw": r.text, "status": r.status_code}
    except Exception as e:
        return {"result_code": "request_exception", "error": str(e)}

def is_success(resp: dict) -> bool:
    return str(resp.get("result_code")) == "1"

# ========= ROUTES =========
@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/sms")
async def sms(req: Request):
    """
    요청 JSON 예:
    {
      "site": "보라매",
      "vd": "2025-11-06",
      "vtLabel": "10:00 ~ 11:00",
      "name": "홍길동",
      "phone": "01012341234",     # 고객 연락처(본문 표기용)
      "sp": "01022844859",        # 관리자(수신자) 번호 (to)
      "memo": ""
    }
    """
    body = await req.json()

    site     = (body.get("site") or "").strip()
    vd       = (body.get("vd") or "").strip()
    vt_label = (body.get("vtLabel") or "").strip()
    name     = (body.get("name") or "").strip()
    phone    = only_digits(body.get("phone"))
    memo     = (body.get("memo") or "").strip()
    admin_sp = only_digits(body.get("sp") or "")   # ← 수신자(to)

    sender_fixed = only_digits(ENV_SENDER)

    # ---- 기본 검증 ----
    if not site:     return {"ok": False, "error": "site 누락"}
    if not vd:       return {"ok": False, "error": "vd(날짜) 누락"}
    if not name:     return {"ok": False, "error": "name 누락"}
    if not phone:    return {"ok": False, "error": "phone(고객 연락처) 누락"}
    if not admin_sp: return {"ok": False, "error": "관리자번호(sp) 누락"}

    if not re.fullmatch(r"\d{9,12}", admin_sp):
        return {"ok": False, "error": "관리자번호(sp) 형식 오류(숫자만 9~12자리)"}
    if not re.fullmatch(r"\d{9,12}", sender_fixed):
        return {"ok": False, "error": "기본 발신번호(ALIGO_SENDER) 형식 오류 또는 미등록"}

    # ---- 본문 구성 ----
    text = build_admin_text(site, vd, vt_label, name, phone, memo)
    title = ""
    if need_lms(text):
        site_disp = site.strip("[]") if site else "예약알림"
        title = f"[{site_disp}] 방문예약"

    # ---- 무조건 고정 발신번호로 전송 (from=ALIGO_SENDER, to=sp) ----
    resp = aligo_send(sender=sender_fixed, receiver=admin_sp, msg=text, title=title)

    if is_success(resp):
        return {"ok": True, "result": resp, "from_used": sender_fixed}
    else:
        # 여기서 실패하면 원인은 거의 잔액부족/점검/차단/제한 등임
        return {"ok": False, "error": "알리고 전송 실패", "detail": resp}
