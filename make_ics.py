"""
Собирает расписание группы РГАУ-МСХА (eg.timacad.ru) в календарь .ics.

Настройки — в блоке ниже. Запуск: python make_ics.py  →  файл timacad.ics
"""
import hashlib
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

# ===== НАСТРОЙКИ =====
GROUP_ID = 1179            # ID группы из адреса страницы (group=1179 → ДВ 03-25)
ACADEMIC_YEAR = 2026       # учебный год: 2026 = 2026/2027
SUBGROUP = 2               # 1 или 2 — чужая подгруппа скрывается; None — показывать всё
CAL_NAME = "Тимирязевка · ДВ 03-25"
OUTPUT = "timacad.ics"
MIN_LESSONS = 5           # защита: если пар меньше — сайт, вероятно, поменялся
# =====================

URL = f"https://eg.timacad.ru/schedule/groups/?academic_year={ACADEMIC_YEAR}&group={GROUP_ID}"
MSK = timezone(timedelta(hours=3))  # Москва, без перехода на летнее время


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (timacad-ics)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def keep_for_subgroup(subject: str) -> bool:
    if SUBGROUP is None:
        return True
    marks = re.findall(r"(\d)\s*п/г", subject)
    if not marks:
        return True                      # общая пара
    if len(marks) > 1:
        return False                     # «склеенная» строка двух подгрупп — дубль
    return int(marks[0]) == SUBGROUP


def parse(html: str):
    soup = BeautifulSoup(html, "html.parser")
    lessons, seen = [], set()
    for day in soup.select(".accordion-item"):
        d = day.select_one(".group-schedule-head-date .fw-semibold")
        if not d:
            continue
        date = datetime.strptime(clean(d.get_text()), "%d.%m.%Y").date()
        for li in day.select("li.group-schedule-lesson-item"):
            subject = clean(li.select_one(".group-schedule-subject").get_text())
            if not keep_for_subgroup(subject):
                continue
            t = clean(li.select_one(".group-schedule-time-range").get_text())
            m = re.match(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", t)
            if not m:
                continue
            h1, m1, h2, m2 = map(int, m.groups())
            teacher = room = ""
            for line in li.select(".group-schedule-meta-line"):
                icon = " ".join(line.i.get("class", [])) if line.i else ""
                text = clean(line.get_text())
                if "bi-person" in icon:
                    teacher = text
                elif "bi-geo-alt" in icon:
                    room = text
            typ = li.select_one(".group-schedule-tag-lesson-type")
            typ = clean(typ.get_text()) if typ else ""
            key = (date, t, subject)
            if key in seen:
                continue
            seen.add(key)
            start = datetime(date.year, date.month, date.day, h1, m1, tzinfo=MSK)
            end = datetime(date.year, date.month, date.day, h2, m2, tzinfo=MSK)
            lessons.append(dict(start=start, end=end, subject=subject,
                                teacher=teacher, room=room, type=typ))
    lessons.sort(key=lambda x: x["start"])
    return lessons


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line: str) -> str:
    """Перенос длинных строк по RFC 5545 (не более 75 байт)."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 74:
            out.append(cur.decode("utf-8"))
            cur = b" " + b
        else:
            cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n".join(out)


def to_ics(lessons) -> str:
    utc = lambda dt: dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//timacad-ics//RU", "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH", f"X-WR-CALNAME:{esc(CAL_NAME)}", "X-WR-TIMEZONE:Europe/Moscow",
        "REFRESH-INTERVAL;VALUE=DURATION:PT4H", "X-PUBLISHED-TTL:PT4H",
    ]
    for l in lessons:
        uid = hashlib.md5(f"{GROUP_ID}|{l['start']}|{l['subject']}".encode()).hexdigest()
        title = l["subject"] + (f" ({l['type']})" if l["type"] else "")
        desc = "\n".join(x for x in [l["type"], l["teacher"]] if x)
        lines += [
            "BEGIN:VEVENT", f"UID:{uid}@timacad-ics", f"DTSTAMP:{utc(l['start'])}",  # постоянный DTSTAMP: файл меняется только при изменении расписания
            f"DTSTART:{utc(l['start'])}", f"DTEND:{utc(l['end'])}",
            f"SUMMARY:{esc(title)}", f"LOCATION:{esc(l['room'])}",
            f"DESCRIPTION:{esc(desc)}", "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(x) for x in lines) + "\r\n"


if __name__ == "__main__":
    html = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else fetch(URL)
    lessons = parse(html)
    if len(lessons) < MIN_LESSONS:
        sys.exit(f"Найдено всего {len(lessons)} пар — похоже, сайт изменился. Старый файл не трогаю.")
    with open(OUTPUT, "w", encoding="utf-8", newline="") as f:
        f.write(to_ics(lessons))
    print(f"OK: {len(lessons)} пар, {lessons[0]['start']:%d.%m.%Y} – {lessons[-1]['start']:%d.%m.%Y}")
