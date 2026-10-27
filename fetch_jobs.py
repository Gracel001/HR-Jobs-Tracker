"""
抓取所有 HR 相关的入门级 / new grad 职位，生成 listings.json 和 README.md
用法: python fetch_jobs.py
依赖: pip install requests
"""
import json
import re
import sys
from datetime import datetime, timezone

import requests

# ---------- 配置 ----------
# True : 带入门词的保留；没有任何资历标记的 HR 职位也保留（结果更多，可能混入中级职位）
# False: 只保留标题里明确带入门词的职位（更精准，但会漏掉一些）
BROAD_MODE = True

# 分类（按顺序匹配，先匹配到的优先）。用正则，\b 表示单词边界
CATEGORIES = {
    "Recruiting & Talent Acquisition": [
        r"recruit", r"talent acquisition", r"sourcer", r"sourcing", r"talent partner",
    ],
    "HR Business Partner & People Partner": [
        r"hr business partner", r"\bhrbp\b", r"people partner", r"hr partner",
        r"people business partner",
    ],
    "HR Analytics, HRIS & Systems": [
        r"hr analytics", r"people analytics", r"workforce analytics", r"\bhris\b",
        r"hr systems", r"hr technology", r"hr data", r"people data", r"hr reporting",
    ],
    "Compensation, Benefits & Payroll": [
        r"compensation", r"benefits", r"total rewards", r"payroll", r"\bhr compliance\b",
    ],
    "Learning, Development & Talent Management": [
        r"learning and development", r"learning & development", r"\bl&d\b",
        r"talent development", r"talent management", r"organizational development",
        r"leadership development", r"training (specialist|coordinator|associate)",
        r"learning (specialist|coordinator|associate|partner)",
    ],
    "Employee Relations, DEI & Culture": [
        r"employee relations", r"labor relations", r"\bdei\b", r"diversity",
        r"inclusion", r"belonging", r"employee experience", r"employee engagement",
        r"culture", r"workplace experience",
    ],
    "People Operations & HR Generalist": [
        r"people operations", r"people ops", r"people (coordinator|associate|specialist|team)",
        r"hr generalist", r"human resources", r"\bhr\b", r"employee (onboarding|lifecycle)",
        r"onboarding (specialist|coordinator)", r"workforce",
    ],
}
OTHER = "Other HR Programs & Roles"   # 兜底：HR 轮岗项目等

# 职位标题里出现这些，视为"入门级 / new grad 友好"
ENTRY_PATTERNS = [
    r"new grad", r"new graduate", r"university", r"early career", r"early talent",
    r"entry", r"associate", r"coordinator", r"junior", r"assistant", r"graduate",
    r"analyst", r"specialist", r"rotational", r"rotation", r"fellow",
    r"development program", r"\bi\b$", r"\b1\b$", r"\bi,",
]
# 出现这些则排除（资深岗位 / 实习）
EXCLUDE_PATTERNS = [
    r"senior", r"\bsr\.?\b", r"manager", r"director", r"head of", r"\bvp\b",
    r"vice president", r"principal", r"staff", r"\blead\b", r"chief",
    r"\bii\b", r"\biii\b", r"\biv\b", r"intern\b", r"internship", r"co-?op",
]

HEADERS = {"User-Agent": "hr-jobs-tracker/1.0"}
TIMEOUT = 20


# ---------- 分类与过滤 ----------
def matches(patterns, text):
    return any(re.search(p, text) for p in patterns)


def categorize(title):
    t = title.lower()
    for cat, pats in CATEGORIES.items():
        if matches(pats, t):
            return cat
    # 标题里有 HR 相关词，但不属于上面任何类
    if matches([r"\bpeople\b", r"\btalent\b", r"human capital", r"employee"], t) \
            and matches([r"program", r"rotation", r"associate", r"graduate", r"fellow"], t):
        return OTHER
    return None


def level_ok(title):
    t = title.lower()
    if matches(EXCLUDE_PATTERNS, t):
        return False
    if matches(ENTRY_PATTERNS, t):
        return True
    return BROAD_MODE


def keep(title):
    cat = categorize(title)
    if cat and level_ok(title):
        return cat
    return None


# ---------- 各招聘平台 ----------
def get_json(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_greenhouse(slug):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    for j in data.get("jobs", []):
        yield {
            "title": j["title"],
            "url": j["absolute_url"],
            "location": (j.get("location") or {}).get("name", ""),
            "date": (j.get("updated_at") or "")[:10],
        }


def fetch_lever(slug):
    for j in get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json"):
        created = j.get("createdAt")
        date = datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if created else ""
        yield {
            "title": j["text"],
            "url": j["hostedUrl"],
            "location": (j.get("categories") or {}).get("location", "") or "",
            "date": date,
        }


def fetch_ashby(slug):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    for j in data.get("jobs", []):
        yield {
            "title": j["title"],
            "url": j.get("jobUrl", ""),
            "location": j.get("location", "") or "",
            "date": (j.get("publishedAt") or "")[:10],
        }


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}


# ---------- 主流程 ----------
def collect(companies):
    jobs = []
    for c in companies:
        fetcher = FETCHERS.get(c["platform"])
        if not fetcher:
            print(f"未知平台: {c}", file=sys.stderr)
            continue
        try:
            found = 0
            for j in fetcher(c["slug"]):
                cat = keep(j["title"])
                if cat:
                    j.update({"company": c["name"], "category": cat})
                    jobs.append(j)
                    found += 1
            print(f"{c['name']}: {found} 个匹配职位")
        except Exception as e:  # 某个公司失败不影响其他公司
            print(f"{c['name']} 抓取失败: {e}", file=sys.stderr)
    jobs.sort(key=lambda x: x["date"], reverse=True)
    return jobs


def build_readme(jobs):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    all_cats = list(CATEGORIES) + [OTHER]
    lines = [
        "# HR New Grad & Entry-Level Positions",
        "",
        "Entry-level and new grad roles across HR: recruiting, HRBP / people partner, "
        "HR analytics, L&D, compensation & benefits, employee relations, people operations, "
        "and more. Updated daily by GitHub Actions.",
        "",
        f"_Last updated: {now}_",
        "",
        f"## Browse {len(jobs)} Roles by Category",
        "",
    ]
    by_cat = {cat: [] for cat in all_cats}
    for j in jobs:
        by_cat[j["category"]].append(j)

    for cat, items in by_cat.items():
        anchor = re.sub(r"[^a-z0-9 -]", "", cat.lower()).replace(" ", "-")
        lines.append(f"- [{cat}](#{anchor}) ({len(items)})")
    lines.append("")

    for cat, items in by_cat.items():
        lines += [f"## {cat}", "", "| Company | Role | Location | Apply | Posted |",
                  "| --- | --- | --- | --- | --- |"]
        for j in items:
            lines.append(f"| {j['company']} | {j['title']} | {j['location']} | [Apply]({j['url']}) | {j['date']} |")
        if not items:
            lines.append("| _No openings right now_ | | | | |")
        lines.append("")
    return "\n".join(lines)


def main():
    with open("companies.json", encoding="utf-8") as f:
        companies = json.load(f)
    jobs = collect(companies)
    with open("listings.json", "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(build_readme(jobs))
    print(f"完成，共 {len(jobs)} 个职位")


if __name__ == "__main__":
    main()
