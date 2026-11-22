"""Preview the dashboard with fake sample data. Never touches your real database.

    python scripts/demo_dashboard.py
    then open http://127.0.0.1:8765/#token=demo-token-not-secret
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

demo_home = Path(tempfile.mkdtemp(prefix="linkreach-demo-"))
os.environ["LINKREACH_HOME"] = str(demo_home)
os.environ["LINKREACH_INPUTS"] = str(demo_home)
shutil.copyfile(ROOT / "linkreach" / "examples" / "config.example.yaml", demo_home / "config.yaml")

import uvicorn  # noqa: E402

from linkreach import clock  # noqa: E402
from linkreach.config import load_inputs  # noqa: E402
from linkreach.dashboard.server import HOST, PORT, create_app  # noqa: E402
from linkreach.db import DB  # noqa: E402

TOKEN = "demo-token-not-secret"
inputs = load_inputs(demo_home)
db = DB.open(demo_home / "linkreach.db")

# People with a connection-request history, as the dormant send path (ADR-0001) records it.
NOTE = ("Hi {f}, your post on onboarding new grads made a 40-step checklist sound like a heist plan. "
        "I rolled out AI tooling to 15+ enterprise clients. Would like to connect.")
people = [
    ("Priya Raman", "Senior Technical Recruiter", "Microsoft", 1, "followed_up", 20),
    ("Marcus Chen", "Director of Product, Azure AI", "Microsoft", 0, "accepted", 12),
    ("Dana Ortiz", "Group Product Manager", "Microsoft", 1, "accepted", 9),
    ("<script>alert('xss')</script>", "Head of Product", "Salesforce", 0, "sent", 3),
    ("Sam Lee", "AI Platform Product Lead", "Salesforce", 0, "sent", 8),
    ("Taylor Brooks", "University Recruiter", "Salesforce", 0, "sent", 10),
    ("Jordan Kim", "Talent Acquisition Partner", "Salesforce", 0, "sent", 15),
    ("Alex Novak", "Senior Product Manager", "Salesforce", 0, "dead", 18),
    ("Riley Patel", "Early Career Recruiter", "Salesforce", 0, "sent", 9),
]
PATHS = {
    "followed_up": ["drafted", "approved", "sent", "accepted", "followed_up"],
    "accepted": ["drafted", "approved", "sent", "accepted"],
    "sent": ["drafted", "approved", "sent"],
    "dead": ["drafted", "approved", "sent", "dead"],
}
for i, (name, title, company, alumni, status, sent_days) in enumerate(people):
    first = name.split()[0] if not name.startswith("<") else "there"
    pid = db.add_person(name=name, title=title, company=company, profile_url=f"https://www.linkedin.com/in/demo-{i}/",
                        is_alumni=alumni, context_1="Posted about new-grad hiring", context_2=title)
    db.update_fields(pid, note_draft=NOTE.format(f=first))
    for st in PATHS[status]:
        extra = {}
        if st == "sent":
            extra = {"sent_at": clock.iso(clock.now() - timedelta(days=sent_days)), "note_sent": NOTE.format(f=first)}
        db.set_status(pid, st, **extra)
    if status == "accepted":
        db.update_fields(pid, follow_up_date=(clock.local_now().date() - timedelta(days=1)).isoformat())
    ts = clock.iso(clock.now() - timedelta(days=sent_days))
    db.conn.execute("INSERT INTO activity_log (timestamp, command, event, person_id, detail) "
                    "VALUES (?, 'send', 'send', ?, 'clicked Send (manual)')", (ts, pid))
    db.conn.commit()
db.update_fields(1, my_notes="Replied fast, wants a call next week")

# A `linkreach job` run that LinkedIn stopped with a security check: the banner shows it.
db.log("job", "run", None, "start job=1 picks=2")
db.log("job", "view", None, "/in/demo-0/")
db.log("job", "captcha", None, "captcha: page text matched 'quick security check'")
db.log("job", "run", None, "end:stopped:captcha")
db.close()

app = create_app(inputs, demo_home / "linkreach.db", token=TOKEN)
print(f"demo data in {demo_home}")
print(f"open http://{HOST}:{PORT}/#token={TOKEN}", flush=True)
uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
