"""ClientLedger — per-client registry for the managed social growth service.

Stores client records and per-client platform credentials in
~/.config/social-poster/clients/<client_id>/.

Variant A: Python-first, zero new infra. Runs from the existing social-poster
package. Credential files mirror the per-adapter session pattern (base.py).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

CLIENTS_DIR = Path.home() / ".config" / "social-poster" / "clients"


@dataclass
class ClientRecord:
    id: str                          # slug e.g. "pizzeria-roma"
    name: str                        # display name
    contact_email: str
    goal: str                        # "fill slow-day tables", "drive DM leads", etc.
    budget_eur_mo: int
    platforms: list[str]             # ["th", "ig"] — social-poster short names
    cta_url: str                     # tracked booking / menu / checkout URL
    slow_days: list[str]             # ["monday", "tuesday"]
    tone: str                        # "friendly", "premium", "energetic"
    baseline_weekly_bookings: int    # measured before service starts
    status: Literal["onboarding", "active", "paused", "cancelled"] = "onboarding"
    started_on: str = field(default_factory=lambda: date.today().isoformat())
    notes: str = ""

    # ── persistence ──

    @property
    def dir(self) -> Path:
        return CLIENTS_DIR / self.id

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "record.json").write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, client_id: str) -> "ClientRecord":
        path = CLIENTS_DIR / client_id / "record.json"
        if not path.exists():
            raise FileNotFoundError(f"No client: {client_id}")
        return cls(**json.loads(path.read_text("utf-8")))

    @classmethod
    def list_all(cls) -> list["ClientRecord"]:
        if not CLIENTS_DIR.exists():
            return []
        records = []
        for p in sorted(CLIENTS_DIR.iterdir()):
            try:
                records.append(cls.load(p.name))
            except (FileNotFoundError, TypeError):
                continue
        return records

    # ── per-client credential paths (adapters read these via env override) ──

    def credential_path(self, platform: str) -> Path:
        """Path where the platform session JSON lives for this client."""
        return self.dir / f"session-{platform}.json"

    def set_env_for_platform(self, platform: str) -> None:
        """Point SOCIAL_POSTER_SESSION_DIR at this client's credential dir.

        Called before SocialPoster().post() so the adapter loads the right
        account token. Resets after the post call.
        """
        os.environ["SOCIAL_POSTER_SESSION_DIR"] = str(self.dir)


# ── CLI helpers ──

def create_client_interactive() -> ClientRecord:
    """One-time interactive onboarding. Run once per new client."""
    print("=== New Client Onboarding ===")
    cid = input("client id (slug, e.g. 'pizzeria-roma'): ").strip()
    name = input("business name: ").strip()
    email = input("contact email: ").strip()
    goal = input("primary goal (e.g. 'fill slow-day tables'): ").strip()
    budget = int(input("monthly budget EUR: ").strip())
    platforms = input("platforms (comma-sep, e.g. 'th,ig'): ").strip().split(",")
    cta = input("CTA URL (booking / menu / checkout): ").strip()
    slow = input("slow days (comma-sep, e.g. 'monday,tuesday'): ").strip().split(",")
    tone = input("tone (friendly/premium/energetic): ").strip()
    baseline = int(input("baseline weekly bookings/leads (0 if unknown): ").strip())
    rec = ClientRecord(
        id=cid, name=name, contact_email=email, goal=goal,
        budget_eur_mo=budget, platforms=[p.strip() for p in platforms],
        cta_url=cta, slow_days=[d.strip() for d in slow],
        tone=tone, baseline_weekly_bookings=baseline,
    )
    rec.save()
    print(f"✓ client '{cid}' saved → {rec.dir}")
    return rec
