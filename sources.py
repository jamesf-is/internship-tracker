"""Job sources. Each fetcher returns a list of raw job dicts:
   title, company, location, url, posted (ISO date or ""), desc (short text), src (label)
Fetchers never raise: failures are reported through the `health` dict.
"""
import datetime as dt
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

import config

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
S = requests.Session()
S.headers.update(UA)
TIMEOUT = 25


def _get(url, **kw):
    return S.get(url, timeout=kw.pop("timeout", TIMEOUT), **kw)


def _iso(ts):
    """epoch seconds / ms / ISO string -> YYYY-MM-DD"""
    if not ts:
        return ""
    try:
        if isinstance(ts, (int, float)):
            if ts > 1e11:
                ts /= 1000
            return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")
        return str(ts)[:10]
    except Exception:
        return ""


def _is_internish(title):
    return re.search(config.INTERN_RE, title or "", re.I) is not None


def _txt(html):
    return re.sub(r"\s+", " ", BeautifulSoup(html or "", "lxml").get_text(" ")).strip()


# ------------------------------------------------------------------ Simplify
def simplify(health):
    label = "simplify"
    try:
        path = os.environ.get("SIMPLIFY_FILE")
        data = json.load(open(path)) if path else _get(config.SIMPLIFY_URL, timeout=90).json()
    except Exception as e:
        health[label] = f"FAIL {e}"[:120]
        return [], set()
    out = []
    for x in data:
        if "Summer 2027" not in (x.get("terms") or []):
            continue
        if not x.get("active") or not x.get("is_visible", True):
            continue
        if x.get("category") not in config.SIMPLIFY_CATEGORIES and not re.search(config.INCLUDE_RE, x.get("title", ""), re.I):
            continue
        out.append(dict(title=x["title"], company=x["company_name"],
                        location="; ".join(x.get("locations") or [])[:120],
                        url=x["url"], posted=_iso(x.get("date_posted")),
                        desc="Summer 2027", src=label, year_confirmed=True))
    health[label] = f"ok ({len(out)} candidates)"
    return out, {label}


# ------------------------------------------------------------------ ATS: board discovery + fetchers
def _slug_candidates(name):
    n = name.lower()
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    words = [w for w in n.split() if w not in
             {"inc", "corp", "corporation", "llc", "company", "co", "group", "the", "technologies", "technology", "industries", "incorporated"}]
    if not words:
        return []
    c = ["".join(words), "-".join(words), words[0]]
    if len(words) > 1:
        c.append("".join(words[:2]))
    seen, res = set(), []
    for s in c:
        if s and len(s) > 2 and s not in seen:
            seen.add(s)
            res.append(s)
    return res


def _same_company(searched, found):
    a, b = re.sub(r"[^a-z0-9]", "", (searched or "").lower()), re.sub(r"[^a-z0-9]", "", (found or "").lower())
    if not a or not b:
        return False
    if a[:6] == b[:6] and min(len(a), len(b)) >= 4:
        return True
    return (len(b) >= 6 and b in a) or (len(a) >= 6 and a in b)


def _first_word(name):
    words = _slug_candidates(name)
    n = re.sub(r"[^a-z0-9 ]", " ", re.sub(r"\(.*?\)", "", name.lower())).split()
    n = [w for w in n if w not in {"inc", "corp", "corporation", "llc", "company", "co", "group", "the", "technologies",
                                    "technology", "industries", "incorporated"}]
    return n[0] if n else ""


def _probe(ats, slug, name=""):
    """Return True if this ATS has a live board for slug that plausibly belongs to `name`."""
    try:
        if ats == "greenhouse":
            r = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout=12)
            if not (r.status_code == 200 and "jobs" in r.json()):
                return False
            info = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}", timeout=12)
            return info.status_code != 200 or _same_company(name, info.json().get("name"))
        if ats == "lever":
            r = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=1", timeout=12)
            return r.status_code == 200 and isinstance(r.json(), list)
        if ats == "ashby":
            r = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=12)
            return r.status_code == 200 and bool(r.json().get("jobs"))
        if ats == "workable":
            with WORKABLE_LOCK:
                time.sleep(0.8)
                r = _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", timeout=12)
            return (r.status_code == 200 and "jobs" in r.json() and bool(r.json().get("name"))
                    and _same_company(name, r.json()["name"]))
        if ats == "smartrecruiters":
            r = _get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1", timeout=12)
            if not (r.status_code == 200 and r.json().get("totalFound", 0) > 0):
                return False
            cn = ((r.json().get("content") or [{}])[0].get("company") or {}).get("name")
            return not cn or _same_company(name, cn)
    except Exception:
        return False
    return False


def discover_boards(names, cache, max_age_days=14):
    """cache: {slug: {"ats":..,"found":date,"checked":date}} ; re-probes misses weekly."""
    today = dt.date.today()
    todo = []
    for name in names:
        for slug in _slug_candidates(name):
            for ats in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters"):
                if ats in ("lever", "ashby") and slug == _first_word(name) and len(_slug_candidates(name)) > 1 \
                        and re.sub(r"[^a-z0-9]", "", name.lower()) != slug:
                    continue  # cannot verify the owner of lever/ashby boards, so only trust full-name slugs
                key = f"{ats}:{slug}"
                c = cache.get(key)
                if c and c.get("v") == 4 and (c["ok"] or dt.date.fromisoformat(c["checked"]) + dt.timedelta(days=max_age_days) > today):
                    continue
                todo.append((key, ats, slug, name))

    def run(t):
        key, ats, slug, name = t
        return key, ats, slug, name, _probe(ats, slug, name)

    with ThreadPoolExecutor(16) as ex:
        for key, ats, slug, name, ok in ex.map(run, todo):
            cache[key] = {"v": 4, "ok": ok, "ats": ats, "slug": slug, "name": name, "checked": today.isoformat()}
    return [v for v in cache.values() if v["ok"]]


def fetch_greenhouse(b):
    r = _get(f"https://boards-api.greenhouse.io/v1/boards/{b['slug']}/jobs")
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        if not _is_internish(j.get("title")):
            continue
        out.append(dict(title=j["title"], company=j.get("company_name") or b["name"],
                        location=(j.get("location") or {}).get("name", ""), url=j["absolute_url"],
                        posted=_iso(j.get("first_published") or j.get("updated_at")), desc="",
                        src=f"greenhouse:{b['slug']}", _gh=(b["slug"], j["id"])))
    # enrich descriptions (to spot "Summer 2027" / other terms) only for intern-titled roles
    for j in out:
        try:
            d = _get(f"https://boards-api.greenhouse.io/v1/boards/{j['_gh'][0]}/jobs/{j['_gh'][1]}", timeout=15).json()
            j["desc"] = _txt(d.get("content", ""))[:1500]
        except Exception:
            pass
        j.pop("_gh", None)
    return out


def fetch_lever(b):
    r = _get(f"https://api.lever.co/v0/postings/{b['slug']}?mode=json")
    r.raise_for_status()
    out = []
    for j in r.json():
        if not _is_internish(j.get("text")):
            continue
        cat = j.get("categories") or {}
        out.append(dict(title=j["text"], company=b["name"], location=cat.get("location", "") or "",
                        url=j["hostedUrl"], posted=_iso(j.get("createdAt")),
                        desc=(j.get("descriptionPlain") or "")[:1500], src=f"lever:{b['slug']}"))
    return out


def fetch_ashby(b):
    r = _get(f"https://api.ashbyhq.com/posting-api/job-board/{b['slug']}")
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        if not _is_internish(j.get("title")):
            continue
        out.append(dict(title=j["title"], company=b["name"], location=j.get("location", "") or "",
                        url=j.get("jobUrl") or j.get("applyUrl"), posted=_iso(j.get("publishedAt")),
                        desc=(j.get("descriptionPlain") or _txt(j.get("descriptionHtml")))[:1500],
                        src=f"ashby:{b['slug']}"))
    return out


def fetch_workable(b):
    url = f"https://apply.workable.com/api/v1/widget/accounts/{b['slug']}?details=true"
    r = _get(url)
    if r.status_code == 429:
        time.sleep(8)
        r = _get(url)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        if not _is_internish(j.get("title")):
            continue
        loc = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        out.append(dict(title=j["title"], company=b["name"], location=loc, url=j.get("url") or j.get("shortlink"),
                        posted=_iso(j.get("published_on")), desc=_txt(j.get("description"))[:1500],
                        src=f"workable:{b['slug']}"))
    return out


def fetch_smartrecruiters(b):
    out = []
    for q in ("intern", "co-op"):
        r = _get(f"https://api.smartrecruiters.com/v1/companies/{b['slug']}/postings?q={q}&limit=100")
        r.raise_for_status()
        for j in r.json().get("content", []):
            if not _is_internish(j.get("name")):
                continue
            loc = j.get("location") or {}
            out.append(dict(title=j["name"], company=(j.get("company") or {}).get("name") or b["name"],
                            location=", ".join(x for x in (loc.get("city"), loc.get("region")) if x),
                            url=f"https://jobs.smartrecruiters.com/{b['slug']}/{j['id']}",
                            posted=_iso(j.get("releasedDate")), desc="", src=f"smartrecruiters:{b['slug']}"))
    return out


ATS_FETCH = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
             "workable": fetch_workable, "smartrecruiters": fetch_smartrecruiters}


import threading
WORKABLE_LOCK = threading.Semaphore(1)
RESOLVED = {}  # tenant -> note, shown in source health


def _wd_post(base, tenant, site, term, offset):
    r = S.post(f"{base}/wday/cxs/{tenant}/{site}/jobs",
               json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": term},
               timeout=TIMEOUT, headers={"Content-Type": "application/json", "Accept": "application/json"})
    r.raise_for_status()
    return r.json().get("jobPostings", [])


def _wd_resolve(tenant, wd):
    """Our guessed site name was wrong: open the tenant's public page and read the real one from the redirect."""
    for w in dict.fromkeys([wd, "wd1", "wd5", "wd3", "wd501", "wd12"]):
        base = f"https://{tenant}.{w}.myworkdayjobs.com"
        try:
            r = _get(base + "/", allow_redirects=True, timeout=15)
        except Exception:
            continue
        if r.status_code >= 400 or "myworkdayjobs.com" not in r.url:
            continue
        segs = [x for x in re.sub(r"^https?://[^/]+", "", r.url.split("?")[0]).split("/") if x]
        segs = [x for x in segs if not re.fullmatch(r"[a-z]{2}-[A-Za-z]{2}", x)]
        if segs:
            return w, segs[0]
    return None


def fetch_workday(w):
    label, tenant, wd, site = w
    out, seen = [], set()
    tried_resolve = False
    while True:
        base = f"https://{tenant}.{wd}.myworkdayjobs.com"
        try:
            for term in ("intern", "co-op"):
                for offset in range(0, 200, 20):
                    posts = _wd_post(base, tenant, site, term, offset)
                    for p in posts:
                        path = p.get("externalPath")
                        if not path or path in seen or not _is_internish(p.get("title")):
                            continue
                        seen.add(path)
                        out.append(dict(title=p["title"], company=label, location=p.get("locationsText", ""),
                                        url=f"{base}/en-US/{site}{path}", posted="", desc=p.get("postedOn", ""),
                                        src=f"workday:{tenant}"))
                    if len(posts) < 20:
                        break
            return out
        except requests.HTTPError as e:
            if tried_resolve or e.response is None or e.response.status_code not in (400, 401, 404, 422):
                raise
            tried_resolve = True
            res = _wd_resolve(tenant, wd)
            if not res or res == (wd, site):
                raise
            wd, site = res
            RESOLVED[tenant] = f"auto-corrected to {wd}/{site}"
            out, seen = [], set()


def parse_successfactors(html, label, base):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for row in soup.select("tr.data-row"):
        a = row.select_one("a.jobTitle-link")
        if not a or not a.get("href"):
            continue
        loc = row.select_one(".jobLocation")
        out.append(dict(title=a.get_text(strip=True), company=label,
                        location=re.sub(r"\s+", " ", loc.get_text(" ", strip=True)).replace(" +", " +") if loc else "",
                        url=base + a["href"].split("?")[0], posted="", desc="", src=f"sf:{label}"))
    m = re.search(r"of\s+(\d+)", (soup.select_one(".paginationLabel") or soup).get_text(" ", strip=True))
    return out, int(m.group(1)) if m else None


def fetch_successfactors(w):
    label, base = w
    out, start = [], 0
    while start < 400:
        r = _get(f"{base}/search/?q=intern&startrow={start}")
        r.raise_for_status()
        rows, total = parse_successfactors(r.text, label, base)
        out += [j for j in rows if _is_internish(j["title"])]
        if not rows or total is None or start + len(rows) >= total:
            break
        start += len(rows)
        time.sleep(1)
    if not out:
        raise RuntimeError("0 postings parsed (site layout may have changed)")
    return out


def parse_linkedin(html):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for li in soup.select("li"):
        a = li.select_one("a.base-card__full-link") or li.select_one("a[href*='/jobs/view/']")
        t = li.select_one(".base-search-card__title")
        c = li.select_one(".base-search-card__subtitle")
        l = li.select_one(".job-search-card__location")
        tm = li.select_one("time")
        if not (a and t):
            continue
        out.append(dict(title=t.get_text(strip=True), company=c.get_text(strip=True) if c else "",
                        location=l.get_text(strip=True) if l else "",
                        url=a["href"].split("?")[0], posted=(tm.get("datetime") if tm else "") or "",
                        desc="", src="linkedin"))
    return out


def linkedin(health):
    import random
    out, fails = [], 0
    secs = config.LINKEDIN_HOURS * 3600
    qs = config.LINKEDIN_QUERIES
    n = min(len(qs), 5)  # a different slice of queries each day keeps request volume low
    day = dt.date.today().toordinal()
    todays = [qs[(day * n + i) % len(qs)] for i in range(n)]
    for q in todays:
        for start in (0, 25):
            url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                   f"?keywords={requests.utils.quote(q)}&location=United%20States&f_E=1&f_TPR=r{secs}&start={start}")
            try:
                r = _get(url)
                if r.status_code == 429:
                    time.sleep(45)
                    r = _get(url)
                if r.status_code == 429:
                    health["linkedin"] = f"rate-limited (partial, {len(out)} raw)"
                    return out, set()
                r.raise_for_status()
                rows = parse_linkedin(r.text)
                out += rows
                if len(rows) < 20:
                    break
            except Exception:
                fails += 1
                break
            time.sleep(random.uniform(4, 8))
        time.sleep(random.uniform(4, 8))
    health["linkedin"] = f"ok ({len(out)} raw, {fails} query failures)" if out else f"no results ({fails} failures)"
    return out, set()


def themuse(health):
    out = []
    try:
        for page in range(0, 10):
            r = _get(f"https://www.themuse.com/api/public/jobs?category=Engineering&category=Science%20and%20Engineering"
                     f"&level=Internship&page={page}")
            r.raise_for_status()
            d = r.json()
            for j in d.get("results", []):
                out.append(dict(title=j["name"], company=(j.get("company") or {}).get("name", ""),
                                location="; ".join(x["name"] for x in j.get("locations", [])),
                                url=(j.get("refs") or {}).get("landing_page", ""), posted=_iso(j.get("publication_date")),
                                desc=_txt(j.get("contents"))[:1500], src="themuse"))
            if page >= d.get("page_count", 0) - 1:
                break
        health["themuse"] = f"ok ({len(out)} raw)"
    except Exception as e:
        health["themuse"] = f"FAIL {e}"[:120]
    return out, set()


def usajobs(health):
    key, email = os.environ.get("USAJOBS_API_KEY"), os.environ.get("USAJOBS_EMAIL")
    if not (key and email):
        health["usajobs"] = "skipped (no API key)"
        return [], set()
    out = []
    try:
        for q in config.USAJOBS_QUERIES:
            r = _get("https://data.usajobs.gov/api/search", params={"Keyword": q, "ResultsPerPage": 50, "DatePosted": 7},
                     headers={"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key})
            r.raise_for_status()
            for it in r.json()["SearchResult"]["SearchResultItems"]:
                d = it["MatchedObjectDescriptor"]
                out.append(dict(title=d["PositionTitle"], company=d.get("OrganizationName", "US Government"),
                                location=d.get("PositionLocationDisplay", ""), url=d["PositionURI"],
                                posted=_iso(d.get("PublicationStartDate")), desc="", src="usajobs"))
        health["usajobs"] = f"ok ({len(out)} raw)"
    except Exception as e:
        health["usajobs"] = f"FAIL {e}"[:120]
    return out, set()


def adzuna(health):
    aid, akey = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (aid and akey):
        health["adzuna"] = "skipped (no API key)"
        return [], set()
    out = []
    try:
        for q in config.ADZUNA_QUERIES:
            for page in (1, 2, 3):
                r = _get(f"https://api.adzuna.com/v1/api/jobs/us/search/{page}",
                         params={"app_id": aid, "app_key": akey, "what": q, "results_per_page": 50,
                                 "max_days_old": 5, "sort_by": "date"})
                r.raise_for_status()
                for j in r.json().get("results", []):
                    out.append(dict(title=j["title"], company=(j.get("company") or {}).get("display_name", ""),
                                    location=(j.get("location") or {}).get("display_name", ""),
                                    url=j["redirect_url"], posted=_iso(j.get("created")),
                                    desc=(j.get("description") or "")[:600], src="adzuna"))
        health["adzuna"] = f"ok ({len(out)} raw)"
    except Exception as e:
        health["adzuna"] = f"FAIL {e}"[:120]
    return out, set()


# ------------------------------------------------------------------ orchestration
def fetch_all(boards_cache, company_names, health):
    """Returns (raw_jobs, ok_snapshot_labels)."""
    jobs, ok_labels = [], set()

    for fn in (simplify, linkedin, themuse, usajobs, adzuna):
        try:
            j, labels = fn(health)
        except Exception as e:  # never let one source kill the run
            health[fn.__name__] = f"FAIL {e}"[:120]
            continue
        jobs += j
        ok_labels |= labels

    boards = discover_boards(company_names, boards_cache)
    health["ats_boards_found"] = f"{len(boards)} boards"

    def run_board(b):
        try:
            return b["ats"] + ":" + b["slug"], ATS_FETCH[b["ats"]](b), None
        except Exception as e:
            return b["ats"] + ":" + b["slug"], [], str(e)[:80]

    def run_wd(w):
        try:
            return "workday:" + w[1], fetch_workday(w), None
        except Exception as e:
            return "workday:" + w[1], [], str(e)[:80]

    def run_sf(w):
        try:
            return "sf:" + w[0], fetch_successfactors(w), None
        except Exception as e:
            return "sf:" + w[0], [], str(e)[:80]

    bad = []
    fast = [b for b in boards if b["ats"] != "workable"]
    slow = [b for b in boards if b["ats"] == "workable"]
    with ThreadPoolExecutor(6) as ex:
        results = (list(ex.map(run_board, fast)) + list(ex.map(run_wd, config.WORKDAY))
                   + list(ex.map(run_sf, config.SUCCESSFACTORS)))
    for b in slow:  # Workable rate-limits bursts, so go one at a time
        results.append(run_board(b))
        time.sleep(2)
    for label, j, err in results:
        if err:
            bad.append(f"{label} ({err})")
        else:
            jobs += j
            ok_labels.add(label)
    health["ats_failed"] = "; ".join(bad) if bad else "none"
    if RESOLVED:
        health["workday_auto_corrected"] = "; ".join(f"{k}: {v}" for k, v in RESOLVED.items())
    return jobs, ok_labels
