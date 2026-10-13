#!/usr/bin/env python3
"""Daily aerospace internship tracker.

  python tracker.py                 # fetch, update data/ + docs/, email new postings if due
  python tracker.py --no-email      # fetch + page only
  python tracker.py --force-email   # send even if already sent today / before 9am ET
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import config

ROOT = Path(__file__).parent
STATE = ROOT / "state.json"
ET = ZoneInfo("America/New_York")

# direct company boards beat aggregators when the same job shows up twice
SRC_PRIORITY = {"greenhouse": 0, "lever": 0, "ashby": 0, "workable": 0, "smartrecruiters": 0, "workday": 0,
                "simplify": 1, "usajobs": 1, "themuse": 2, "adzuna": 3, "linkedin": 2}


# ------------------------------------------------------------------ filtering
def norm_company(c):
    c = re.sub(r"\(.*?\)", "", (c or "").lower())
    c = re.sub(r"[^a-z0-9 ]", " ", c)
    c = re.sub(r"\b(inc|corp|corporation|llc|ltd|company|co|group|the|technologies|technology|incorporated)\b", " ", c)
    return re.sub(r"\s+", "", c)


def job_key(j):
    city = re.split(r"[,;(]", j.get("location") or "")[0].strip().lower()
    t = re.sub(r"[^a-z0-9]", "", (j["title"] or "").lower())
    return hashlib.sha1(f"{norm_company(j['company'])}|{t}|{city}".encode()).hexdigest()[:16]


def classify(j, aero_companies=frozenset()):
    """Return (keep, year_confirmed)."""
    title = j.get("title") or ""
    text = f"{title} {j.get('desc') or ''}"
    if not re.search(config.INTERN_RE, title, re.I):
        return False, False
    if re.search(config.EXCLUDE_RE, title, re.I):
        return False, False
    if re.search(config.NON_US_RE, j.get("location") or "", re.I):
        return False, False
    has_target = config.TARGET_YEAR in text or j.get("year_confirmed")
    # explicit other-term (fall 2026, summer 2026, spring 2027 ...) => drop, unless it also names summer 2027
    if re.search(config.OTHER_TERM_RE, text, re.I) and not re.search(r"summer\s*'?(20)?27", text, re.I):
        return False, False
    if re.search(r"\b20(24|25|26)\b", title) and config.TARGET_YEAR not in title:
        return False, False
    ctx = f"{j.get('company', '')} {j.get('desc', '')}"
    n = norm_company(j.get("company"))
    aero_ctx = (any(n.startswith(a[:10]) or a.startswith(n[:10]) for a in aero_companies if len(a) > 4 and len(n) > 4)
                or re.search(config.AERO_CONTEXT_RE, ctx, re.I) is not None)
    relevant = re.search(config.STRONG_RE, title, re.I) is not None
    if not relevant and aero_ctx:
        relevant = (re.search(config.WEAK_RE, title, re.I) is not None
                    or re.search(config.GENERIC_ENG_RE, title, re.I) is not None)
    return relevant, bool(has_target)


# ------------------------------------------------------------------ state
def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"jobs": {}, "boards": {}, "last_email_date": "", "runs": 0}


def merge(state, raw, ok_labels, aero_companies, now):
    today = now.date().isoformat()
    seen_keys = set()
    for j in raw:
        keep, yc = classify(j, aero_companies)
        if not keep or not j.get("url"):
            continue
        k = job_key(j)
        seen_keys.add(k)
        prio = SRC_PRIORITY.get(j["src"].split(":")[0], 5)
        cur = state["jobs"].get(k)
        rec = dict(title=j["title"].strip(), company=j["company"].strip(), location=(j.get("location") or "").strip(),
                   url=j["url"], src=j["src"], prio=prio, posted=j.get("posted") or "", year_confirmed=yc)
        if cur is None:
            rec.update(first_seen=today, last_seen=today, emailed=False, closed=False)
            state["jobs"][k] = rec
        else:
            if prio < cur.get("prio", 9):  # upgrade to the better link
                cur.update(url=rec["url"], src=rec["src"], prio=prio)
            cur["year_confirmed"] = cur.get("year_confirmed") or yc
            cur["posted"] = cur.get("posted") or rec["posted"]
            cur["last_seen"] = today
            cur["closed"] = False
    # close postings that vanished from a source we fully fetched this run
    for k, rec in state["jobs"].items():
        if k in seen_keys:
            continue
        if rec["src"] in ok_labels:
            rec["closed"] = True
        else:
            first = dt.date.fromisoformat(rec["first_seen"])
            if (now.date() - first).days > config.STALE_DAYS_NONSNAPSHOT and rec["src"] not in ok_labels:
                rec["closed"] = True


# ------------------------------------------------------------------ rendering
def open_jobs(state):
    js = [dict(v, key=k) for k, v in state["jobs"].items() if not v.get("closed")]
    js.sort(key=lambda r: (r["first_seen"], r.get("posted", "")), reverse=True)
    return js


def render_page(state, health, companies, now):
    jobs = open_jobs(state)
    today = now.date()
    for j in jobs:
        j["new"] = (today - dt.date.fromisoformat(j["first_seen"])).days <= 1
    payload = json.dumps([{k: j[k] for k in ("title", "company", "location", "url", "first_seen", "posted", "year_confirmed", "new", "src")}
                          for j in jobs])
    career = "".join(f'<a href="{html.escape(c["careers_url"])}" target="_blank" rel="noopener">{html.escape(c["company"])}</a>'
                     for c in companies if c.get("careers_url"))
    hl = "".join(f"<li><b>{html.escape(k)}</b>: {html.escape(str(v))}</li>" for k, v in health.items())
    tpl = (ROOT / "template.html").read_text()
    out = (tpl.replace("__JOBS__", payload.replace("</", "<\\/"))
              .replace("__UPDATED__", now.strftime("%b %d, %Y %I:%M %p ET"))
              .replace("__CAREERS__", career).replace("__HEALTH__", hl))
    (ROOT / "index.html").write_text(out)


def build_email(new_jobs, total, page_url, health, first_run):
    n = len(new_jobs)
    shown = new_jobs[:config.EMAIL_MAX_ROWS]
    rows = ""
    for j in shown:
        badge = "" if j["year_confirmed"] else ' <span style="color:#a15c00">(year not stated)</span>'
        rows += (f'<tr><td style="padding:8px 10px;border-bottom:1px solid #eee"><b>{html.escape(j["company"])}</b><br>'
                 f'{html.escape(j["title"])}{badge}<br><span style="color:#666;font-size:12px">{html.escape(j["location"])}</span></td>'
                 f'<td style="padding:8px 10px;border-bottom:1px solid #eee;white-space:nowrap">'
                 f'<a href="{html.escape(j["url"])}" style="background:#0b5fff;color:#fff;padding:6px 12px;border-radius:5px;text-decoration:none">Apply</a></td></tr>')
    more = f'<p>+ {n - len(shown)} more on the page.</p>' if n > len(shown) else ""
    bad = [k for k, v in health.items() if str(v).startswith("FAIL")]
    warn = f'<p style="color:#a15c00">Sources that failed today: {", ".join(bad)}</p>' if bad else ""
    head = (f"First run: {n} open Summer 2027 postings found." if first_run else f"{n} new posting{'s' if n != 1 else ''} since yesterday.")
    body = (f'<div style="font-family:Arial,sans-serif;max-width:680px"><h2 style="margin-bottom:4px">Aerospace internships</h2>'
            f'<p style="margin-top:0;color:#555">{head} {total} open in total. '
            f'<a href="{html.escape(page_url)}">Open full list</a></p>'
            f'<table style="border-collapse:collapse;width:100%">{rows}</table>{more}{warn}</div>')
    text = head + "\n\n" + "\n".join(f'{j["company"]} | {j["title"]} | {j["location"]}\n  {j["url"]}' for j in shown)
    subj = f"{n} new aerospace internship{'s' if n != 1 else ''} (Summer 2027)" if not first_run else f"Your aerospace internship list is live ({n} postings)"
    return subj, body, text


def send_email(subject, html_body, text_body):
    user, pw, to = os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"], os.environ["TO_EMAIL"]
    m = MIMEMultipart("alternative")
    m["Subject"], m["From"], m["To"] = subject, user, to
    m.attach(MIMEText(text_body, "plain"))
    m.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, pw)
        s.sendmail(user, [to], m.as_string())


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--force-email", action="store_true")
    ap.add_argument("--email-preview", help="write the email HTML here instead of sending")
    a = ap.parse_args()

    import sources  # imported late so tests can import classify without network libs

    now = dt.datetime.now(ET)
    state = load_state()
    companies = json.loads((ROOT / "companies.json").read_text())
    names = sorted({c["company"] for c in companies} | set(config.EXTRA_COMPANIES))
    aero = {norm_company(n) for n in names}
    health = {}

    raw, ok_labels = sources.fetch_all(state["boards"], names, health)
    merge(state, raw, ok_labels, aero, now)
    state["runs"] += 1
    health["last_run"] = now.isoformat(timespec="minutes")
    health["open_postings"] = str(len(open_jobs(state)))

    render_page(state, health, companies, now)

    page_url = os.environ.get("PAGE_URL", "https://YOUR-USERNAME.github.io/internship-tracker/")
    pending = [j for j in open_jobs(state) if not state["jobs"][j["key"]]["emailed"]]
    due = a.force_email or (now.hour >= 9 and state["last_email_date"] != now.date().isoformat())
    if not a.no_email and due and pending:
        subj, body, text = build_email(pending, len(open_jobs(state)), page_url, health, first_run=state["last_email_date"] == "")
        if a.email_preview:
            Path(a.email_preview).write_text(body)
            print("email preview written:", subj)
        else:
            send_email(subj, body, text)
            print("email sent:", subj)
        for j in pending:
            state["jobs"][j["key"]]["emailed"] = True
        state["last_email_date"] = now.date().isoformat()
    else:
        print(f"no email (due={due}, pending={len(pending)})")

    STATE.write_text(json.dumps(state, indent=1))
    print(json.dumps(health, indent=1))


if __name__ == "__main__":
    main()
