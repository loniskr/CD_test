import os
import sys
import json
import base64
import datetime
import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
URL = "https://www.kopo.ac.kr/gm/content.do?menu=12623"
WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

# 저장소 안에서 캐시/이미지를 둘 폴더
DATA_DIR = "data"        # data/2026-06-08.json  (칼로리·이미지경로 기록)
IMAGE_DIR = "images"     # images/2026-06-08.png (생성된 밥상 이미지)

# 본인 저장소에 맞게 수정 (raw 이미지 URL 만들 때 사용)
GH_OWNER = "loniskr"
GH_REPO = "CD_test"
GH_BRANCH = "main"

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TEAMS_WEBHOOK = os.environ.get("TEAMS_WEBHOOK")


# ─────────────────────────────────────────────
# 1. 메뉴 스크래핑
# ─────────────────────────────────────────────
def fetch_menu():
    """오늘 요일의 중식 메뉴를 (요일명, [메뉴리스트]) 로 반환."""
    resp = requests.get(URL, headers=SCRAPE_HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")

    target = None
    for table in soup.find_all("table"):
        text = table.get_text()
        if "중식" in text and "월요일" in text:
            target = table
            break
    if target is None:
        return None, []

    today_name = WEEKDAYS[datetime.datetime.now().weekday()]
    for row in target.find_all("tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if not cells:
            continue
        if cells[0] == today_name:
            lunch = cells[2] if len(cells) > 2 else ""
            items = [x.strip() for x in lunch.split(",") if x.strip()]
            return today_name, items

    return today_name, []


# ─────────────────────────────────────────────
# 2. 칼로리·영양 추정 (OpenAI 텍스트)
# ─────────────────────────────────────────────
def estimate_nutrition(menu_items):
    """메뉴를 보고 대략 칼로리/코멘트를 JSON으로 받아온다."""
    menu_str = ", ".join(menu_items)
    prompt = (
        "다음은 한국 구내식당의 점심 메뉴야. 한 끼 기준 대략적인 총 칼로리와 "
        "영양에 대한 짧은 코멘트를 추정해줘. 정확한 수치가 아니라 대략적인 추정이야.\n"
        f"메뉴: {menu_str}\n\n"
        "반드시 아래 JSON 형식으로만, 다른 말 없이 답해:\n"
        '{"kcal": "약 700kcal", "comment": "튀김류가 있어 다소 무거운 편이에요"}'
    )

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        },
        timeout=30,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    return data.get("kcal", "추정 불가"), data.get("comment", "")


# ─────────────────────────────────────────────
# 3. 메뉴 이미지 생성 (OpenAI 이미지) → 파일로 저장
# ─────────────────────────────────────────────
def generate_image(menu_items, save_path):
    """밥상 이미지를 생성해 save_path(png)로 저장."""
    menu_str = ", ".join(menu_items)
    prompt = (
        f"한국 학교 급식 스테인리스 6칸 배식판을 바로 위에서 내려다본 실제 사진. "
        "배식판 구조: 아래쪽에 큰 칸 2개(왼쪽 밥칸, 오른쪽 국칸), "
        "그 위 좌우에 깊은 반찬칸 1개씩, 가운데에 얕은 반찬칸 2개. "
        f"각 칸에 담긴 음식: {menu_str}. "
        "왼쪽 아래 큰 칸에는 밥, 오른쪽 아래 큰 칸에는 국물 요리. "
        "반찬은 칸마다 색과 형태가 분명히 다르게, 김치는 붉고 매콤한 색으로 구분. "
        "형광등 아래 급식실 분위기, 실제 DSLR 음식 사진, 일러스트나 3D 렌더링 아님."
    )

    resp = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-image-1",
            "prompt": prompt,
            "size": "1024x1024",
            "quality": "high",   # 비용 절약 (low/medium/high)
            "n": 1,
        },
        timeout=120,
    )
    resp.raise_for_status()
    b64 = resp.json()["data"][0]["b64_json"]
    with open(save_path, "wb") as f:
        f.write(base64.b64decode(b64))


# ─────────────────────────────────────────────
# 4. Teams 전송
# ─────────────────────────────────────────────
def send_to_teams(title, menu_items, kcal, comment, image_url):
    body = [
        {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium"},
    ]

    # 메뉴 본문
    if menu_items:
        menu_text = "\n".join(f"• {m}" for m in menu_items)
    else:
        menu_text = "오늘은 등록된 중식 메뉴가 없습니다."
    body.append({"type": "TextBlock", "text": menu_text, "wrap": True})

    # 이미지
    if image_url:
        body.append({"type": "Image", "url": image_url, "size": "Large"})

    # 칼로리
    if kcal:
        body.append(
            {
                "type": "TextBlock",
                "text": f"🔥 {kcal} · {comment}",
                "wrap": True,
                "spacing": "Small",
            }
        )
        body.append(
            {
                "type": "TextBlock",
                "text": "※ AI 추정치, 참고용이에요",
                "wrap": True,
                "isSubtle": True,
                "size": "Small",
            }
        )

    # 반응 유도
    body.append(
        {
            "type": "TextBlock",
            "text": "오늘 메뉴 어때요? 👍 먹는다 / 👎 패스 — 이모지로 반응 주세요!",
            "wrap": True,
            "spacing": "Medium",
        }
    )

    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": body,
                },
            }
        ],
    }
    r = requests.post(TEAMS_WEBHOOK, json=payload, timeout=15)
    print("Teams 응답:", r.status_code, r.text[:200])
    r.raise_for_status()


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main():
    if not TEAMS_WEBHOOK:
        print("TEAMS_WEBHOOK 없음", file=sys.stderr)
        sys.exit(1)

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_name = WEEKDAYS[datetime.datetime.now().weekday()]
    title = f"🍱 오늘의 점심 ({today} {today_name})"

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)

    cache_path = os.path.join(DATA_DIR, f"{today}.json")
    image_path = os.path.join(IMAGE_DIR, f"{today}.png")
    image_url = (
        f"https://raw.githubusercontent.com/{GH_OWNER}/{GH_REPO}/"
        f"{GH_BRANCH}/{IMAGE_DIR}/{today}.png"
    )

    # ── 캐시 있으면 그대로 재사용 (OpenAI 호출 안 함) ──
    if os.path.exists(cache_path):
        print("캐시 사용:", cache_path)
        with open(cache_path, encoding="utf-8") as f:
            c = json.load(f)
        send_to_teams(
            title, c["menu"], c.get("kcal"), c.get("comment"),
            c.get("image_url") if os.path.exists(image_path) else None,
        )
        return

    # ── 신규 생성 ──
    day, menu_items = fetch_menu()

    if not menu_items:
        # 메뉴 없으면 AI 호출 없이 안내만
        print("메뉴 없음 — AI 생성 건너뜀")
        send_to_teams(title, [], None, None, None)
        # 캐시도 남겨서 같은 날 재호출 방지
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"menu": [], "kcal": None, "comment": None,
                       "image_url": None}, f, ensure_ascii=False)
        return

    print("메뉴:", menu_items)

    # 칼로리
    kcal, comment = None, None
    if OPENAI_API_KEY:
        try:
            kcal, comment = estimate_nutrition(menu_items)
            print("칼로리:", kcal, comment)
        except Exception as e:
            print("칼로리 추정 실패:", e, file=sys.stderr)

    # 이미지
    have_image = False
    if OPENAI_API_KEY:
        try:
            generate_image(menu_items, image_path)
            have_image = True
            print("이미지 생성 완료:", image_path)
        except Exception as e:
            print("이미지 생성 실패:", e, file=sys.stderr)

    # 캐시 기록
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "menu": menu_items,
                "kcal": kcal,
                "comment": comment,
                "image_url": image_url if have_image else None,
            },
            f,
            ensure_ascii=False,
        )

    send_to_teams(
        title, menu_items, kcal, comment,
        image_url if have_image else None,
    )


if __name__ == "__main__":
    main()
