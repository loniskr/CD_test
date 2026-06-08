import os
import sys
import datetime
import requests
from bs4 import BeautifulSoup

URL = "https://www.kopo.ac.kr/gm/content.do?menu=12623"
WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def fetch_menu():
    """식단 페이지에서 오늘 요일의 중식 메뉴를 가져온다."""
    resp = requests.get(URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "html.parser")

    # 구분/조식/중식/석식 헤더를 가진 식단 테이블 찾기
    target = None
    for table in soup.find_all("table"):
        text = table.get_text()
        if "중식" in text and "월요일" in text:
            target = table
            break
    if target is None:
        return None, "식단 테이블을 찾지 못했습니다."

    # 오늘 요일 인덱스 (월=0 ... 일=6)
    today_idx = datetime.datetime.now().weekday()
    today_name = WEEKDAYS[today_idx]

    # 행을 돌면서 오늘 요일 행 찾기
    for row in target.find_all("tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if not cells:
            continue
        if cells[0] == today_name:
            # 보통 [구분, 조식, 중식, 석식] 순서 → index 2가 중식
            lunch = cells[2] if len(cells) > 2 else ""
            return today_name, (lunch.strip() or "오늘은 등록된 중식 메뉴가 없습니다.")

    return today_name, "오늘 요일의 식단을 찾지 못했습니다."


def send_to_teams(title, body):
    webhook = os.environ.get("TEAMS_WEBHOOK")
    if not webhook:
        print("TEAMS_WEBHOOK 환경변수가 없습니다.", file=sys.stderr)
        sys.exit(1)

    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": title,
                            "weight": "Bolder",
                            "size": "Medium",
                        },
                        {"type": "TextBlock", "text": body, "wrap": True},
                    ],
                },
            }
        ],
    }
    r = requests.post(webhook, json=payload, timeout=15)
    print("Teams 응답:", r.status_code, r.text[:200])
    r.raise_for_status()


def main():
    day, menu = fetch_menu()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    title = f"🍱 오늘의 점심 ({today} {day})"
    print(title)
    print(menu)
    send_to_teams(title, menu)


if __name__ == "__main__":
    main()