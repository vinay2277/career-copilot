"""Seed the local database with a demo profile and job board.

Runs entirely through the HTTP API and needs no Anthropic credentials: jobs go
in via `/api/extract/confirm`, which takes an already-validated payload, so the
two ingestion agents stay out of the path.

    python scripts/seed_demo.py                 # against localhost:8000
    python scripts/seed_demo.py --base http://localhost:8000
    python scripts/seed_demo.py --email me@example.com --password ...

It registers a demo student (or signs in, if that account already exists) and
seeds against it: the data belongs to an account, so it has to own one.

To start over, stop the server and delete `career_copilot.db`.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

PROFILE = {
    "full_name": "Vinay",
    "headline": "Backend engineer, payments",
    "years_experience": 4.0,
    "career_goal": (
        "Move into a senior backend role at a product company, ideally working "
        "on infrastructure rather than feature work."
    ),
    "skills": [
        {"name": "Python", "proficiency": "proficient", "years": 4.0},
        {"name": "FastAPI", "proficiency": "proficient", "years": 3.0},
        {"name": "Postgres", "proficiency": "working", "years": 3.0},
        {"name": "Docker", "proficiency": "working", "years": 2.0},
        {"name": "Redis", "proficiency": "working", "years": 2.0},
        {"name": "JS", "proficiency": "working", "years": 2.0},
        {"name": "Kubernetes", "proficiency": "learning", "years": 0.5},
    ],
    "preferences": {
        "target_roles": ["backend engineer", "platform engineer"],
        "locations": ["Bengaluru", "Remote"],
        "remote_ok": True,
        "seniority": "senior",
        "min_salary": 2800000,
        "currency": "INR",
        "company_sizes": ["medium", "large"],
        "industries": ["fintech", "developer tools"],
    },
}


def job(
    title: str,
    company: str,
    requirements: list[tuple[str, str, float]],
    *,
    location: str = "Remote",
    remote: bool = True,
    seniority: str = "senior",
    salary: tuple[int, int] = (2_800_000, 4_200_000),
    industry: str = "fintech",
    size: str = "medium",
    confidence: float = 0.93,
    unverified: list[str] | None = None,
) -> dict:
    """Build a confirmed-extraction payload."""
    return {
        "title": title,
        "company": company,
        "location": location,
        "remote": remote,
        "seniority": seniority,
        "salary_min": salary[0],
        "salary_max": salary[1],
        "currency": "INR",
        "industry": industry,
        "company_size": size,
        "description": f"{title} at {company}.",
        "requirements": [
            {
                "name": name,
                "necessity": necessity,
                "min_years": years,
                "evidence": f"posting mentions {name}",
            }
            for name, necessity, years in requirements
        ],
        "source_kind": "text",
        "source_url": None,
        "raw_text": (
            f"{title} at {company}. {location}. "
            f"Looking for: {', '.join(n for n, _, _ in requirements)}."
        ),
        "confidence": confidence,
        "unverified_fields": unverified or [],
        "contradicted_fields": [],
        "validation_notes": (
            "All fields grounded in the source."
            if not unverified
            else f"Could not confirm: {', '.join(unverified)}."
        ),
        "needs_confirmation": bool(unverified),
    }


REQUIRED, PREFERRED, NICE = "required", "preferred", "nice_to_have"

JOBS = [
    (
        job(
            "Senior Backend Engineer",
            "Razorpay",
            [
                ("python", REQUIRED, 3),
                ("postgresql", REQUIRED, 2),
                ("kubernetes", REQUIRED, 2),
                ("terraform", PREFERRED, 0),
            ],
            location="Bengaluru",
            remote=False,
        ),
        # Moved along the pipeline so the funnel has something to measure.
        ["applied", "screening"],
    ),
    (
        job(
            "Platform Engineer",
            "Zerodha",
            [
                ("python", REQUIRED, 4),
                ("kubernetes", REQUIRED, 3),
                ("terraform", REQUIRED, 2),
                ("aws", REQUIRED, 2),
                ("go", PREFERRED, 0),
            ],
            salary=(3_200_000, 4_800_000),
        ),
        ["applied"],
    ),
    (
        job(
            "Backend Engineer, Payments",
            "Stripe",
            [
                ("python", REQUIRED, 3),
                ("postgresql", REQUIRED, 3),
                ("redis", PREFERRED, 0),
                ("kafka", PREFERRED, 0),
            ],
            salary=(4_000_000, 6_000_000),
            size="large",
            confidence=0.62,
            unverified=["salary_max", "company_size"],
        ),
        ["applied", "screening", "interviewing"],
    ),
    (
        job(
            "Senior Software Engineer",
            "Atlassian",
            [
                ("java", REQUIRED, 5),
                ("spring", REQUIRED, 3),
                ("postgresql", PREFERRED, 0),
            ],
            industry="developer tools",
            size="large",
            salary=(3_500_000, 5_000_000),
        ),
        [],  # stays saved — low alignment, nothing done with it
    ),
    (
        job(
            "Infrastructure Engineer",
            "Postman",
            [
                ("kubernetes", REQUIRED, 2),
                ("terraform", REQUIRED, 2),
                ("aws", REQUIRED, 3),
                ("python", PREFERRED, 0),
                ("prometheus", NICE, 0),
            ],
            industry="developer tools",
        ),
        ["applied"],
    ),
    (
        job(
            "Staff Backend Engineer",
            "CRED",
            [
                ("python", REQUIRED, 6),
                ("postgresql", REQUIRED, 4),
                ("kubernetes", REQUIRED, 3),
                ("system design", REQUIRED, 5),
            ],
            seniority="staff",
            salary=(5_000_000, 7_000_000),
        ),
        ["applied", "rejected"],
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--email", default="demo@example.com")
    parser.add_argument("--password", default="demo-password-123")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    # Every /api route needs a session now, so the seeded data has to belong to
    # an account. urllib drops cookies unless an opener holds a jar.
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def call(method: str, path: str, body: object | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with opener.open(req, timeout=30) as r:
            return json.loads(r.read() or "null")

    try:
        call("GET", "/health")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"Cannot reach {base} — is the backend running?\n  {e}", file=sys.stderr)
        return 1

    credentials = {"email": args.email, "password": args.password}
    try:
        call("POST", "/api/auth/register/student", {**credentials, "full_name": "Demo"})
        print(f"registered {args.email}")
    except urllib.error.HTTPError as e:
        # 409 means it already exists, which is the normal case on a re-run.
        if e.code != 409:
            raise
        call("POST", "/api/auth/login", credentials)
        print(f"signed in as {args.email}")

    profile = call("PUT", "/api/profile", PROFILE)
    print(f"profile: {profile['full_name']}, {len(profile['skills'])} skills")

    for payload, transitions in JOBS:
        created = call("POST", "/api/extract/confirm", payload)
        for status in transitions:
            call(
                "PATCH",
                f"/api/opportunities/{created['id']}/application",
                {"status": status},
            )
        trail = " -> ".join(["saved", *transitions])
        print(f"  {created['title']} @ {created['company']}: {trail}")

    board = call("GET", "/api/opportunities")
    rois = call("GET", "/api/skill-roi")
    funnel = call("GET", "/api/analytics/funnel")

    print(f"\n{len(board)} jobs on the board:")
    for item in sorted(board, key=lambda o: -o["alignment"]["total"]):
        print(
            f"  {item['alignment']['total']:5.1f}  {item['job']['title']}"
            f" @ {item['job']['company']}  [{item['status']}]"
        )

    print("\ntop skill payoffs:")
    for r in rois[:5]:
        print(
            f"  {r['skill']:14} asked by {r['demand']}, unlocks "
            f"{r['unlock_count']}, mean +{r['mean_gain']}"
        )

    print(
        f"\nfunnel: response rate {funnel['response_rate']}, "
        f"offer rate {funnel['offer_rate']}"
    )
    if funnel["bottleneck"]:
        b = funnel["bottleneck"]
        print(
            f"  weakest transition: into {b['status']} at "
            f"{b['conversion_from_previous']:.0%}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
