#!/usr/bin/env python3
"""One-shot seed: writes Abraham's profile into the user_profile table.
Safe to re-run — uses upsert on user_id.
Run: python3 scripts/seed_profile.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "worker"))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "apps", "worker", ".env"))
from supabase import create_client
client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
users = client.auth.admin.list_users()
if not users:
    print("No users found. Log in to the app first.")
    sys.exit(1)
user = users[0]
print(f"Seeding profile for: {user.email}")
PROFILE_CONTENT = """# About Me
**Name:** Abraham
**Location:** Sydney, Australia (UTC+10, Australia/Sydney)
**Native country:** India. Parents live in Oman — regular family contact matters.
## Current Life Stage
Recently completed a Masters in Manufacturing and Management at UNSW Sydney.
Now transitioning into earning and building simultaneously — no longer a student.
## Work & Business
- **Current role:** Private tutor at JDN Tuitions — travels to students' homes to teach
- **Subjects:** Mathematics, Science, Engineering fundamentals (high school / early university)
- **Goal 1:** Grow the private tutoring into a standalone business
- **Goal 2:** Plan and launch a broader business venture (still forming)
## Daily Structure
- **Morning:** Personal routine, read Sunday's brief, plan the day
- **Afternoon:** Tutoring sessions at students' homes across Sydney
- **Evening:** Business planning, learning, admin, family calls to Oman/India
## Priorities Sunday should always know
1. Tutoring session schedule and student prep
2. Business planning tasks and follow-ups
3. Financial awareness — income is just starting, spend carefully
4. Family calls — flag if it has been more than a few days since contact
5. Health and daily routine — gym, sleep, meals
## Preferences
- Brief tone: concise, direct, motivating — no filler
- Notifications: push via ntfy (topic: sunday-abc123)
- Approvals: always ask before sending emails or booking anything
- Language: English
"""
res = client.table("user_profile").upsert(
    {"user_id": user.id, "content": PROFILE_CONTENT},
    on_conflict="user_id"
).execute()
if res.data:
    print("✅ Profile seeded.")
else:
    print(f"❌ Failed: {res}")
