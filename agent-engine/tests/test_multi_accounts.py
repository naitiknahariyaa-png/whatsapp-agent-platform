"""Multi-Account Manager tests: profile setup, parallel run, business-only copy."""
import asyncio
import json
import os
import sys
import tempfile

import pytest

from multi_accounts import (load_profiles, setup_accounts, list_accounts,
                            build_account_message, run_all)

PROFILES = [
    {"business_name": "Dr Asha Clinic", "vertical": "doctor",
     "whatsapp_number": "+919111111001", "brand_voice": "formal",
     "services": ["Skin consultation", "Laser therapy"],
     "contacts": [{"name": "Ramesh", "phone": "+919888777111"},
                  {"name": "Suresh", "phone": "+919888777112"}]},
    {"business_name": "Glow and Go Salon", "vertical": "salon",
     "whatsapp_number": "+919111111002", "brand_voice": "playful",
     "services": ["Haircut and styling", "Bridal package"],
     "contacts": [{"name": "Anita", "phone": "+919888777222"}]},
    {"business_name": "Spice Junction", "vertical": "restaurant",
     "whatsapp_number": "+919111111003", "brand_voice": "casual",
     "services": ["North Indian thali"],
     "contacts": [{"name": "Vikram", "phone": "+919888777333"}]},
]


def _write_profiles(tmpdir, profiles):
    p = os.path.join(tmpdir, "profiles.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(profiles, f)
    return p


def test_load_and_setup_and_list():
    async def _go():
        from db import init_db
        await init_db()
        with tempfile.TemporaryDirectory() as td:
            path = _write_profiles(td, PROFILES)
            assert len(load_profiles(path)) == 3
            res = await setup_accounts(path)
            assert res["ok"] and len(res["created"]) == 3
            # duplicate numbers are skipped on re-run
            res2 = await setup_accounts(path)
            assert len(res2["created"]) == 0 and len(res2["skipped"]) == 3
        accounts = await list_accounts()
        names = {a["business_name"] for a in accounts}
        assert {"Dr Asha Clinic", "Glow and Go Salon"} <= names
        doc = next(a for a in accounts if a["business_name"] == "Dr Asha Clinic")
        assert doc["contacts"] == 2 and doc["vertical"] == "doctor"
        return res
    asyncio.run(_go())


def test_copy_is_business_only_and_le160():
    doc = {"business_name": "Dr Asha Clinic", "vertical": "doctor",
           "brand_voice": "formal", "services": ["Skin consultation"],
           "business_hours": "Mon-Sat 10:00-19:00"}
    salon = {"business_name": "Glow and Go Salon", "vertical": "salon",
             "services": ["Bridal package"]}
    m = build_account_message(doc, {"name": "Ramesh Kumar", "phone": "+91"})
    assert m.startswith("Hi Ramesh") and "Dr Asha Clinic" in m
    assert len(m) <= 160
    # never leaks the other account's business/services
    assert "Glow" not in m and "Bridal" not in m
    m2 = build_account_message(salon, {"name": "", "phone": "+91"})
    assert "Hey" in m2 or "Hi there" in m2 or "there" in m2
    assert "Asha" not in m2 and "Skin" not in m2
    # <=160 even with a very long business name + hours
    long = {**doc, "business_name": "Dr Asha Super Speciality Skin Laser "
                                 "and Hair Transplant Clinic Pvt Ltd Meerut",
            "business_hours": "Mon-Sat 10:00-19:00 emergency 24x7"}
    assert len(build_account_message(long, {"name": "Ramesh", "phone": "+91"})) <= 160


def test_parallel_run_all_simulate():
    async def _go():
        from db import init_db
        await init_db()
        with tempfile.TemporaryDirectory() as td:
            path = _write_profiles(td, PROFILES)
            await setup_accounts(path)
        statuses = []
        async def on_status(cid, biz, i, tot, phone, kind, text):
            statuses.append((cid, biz, kind))
        res = await run_all(mode="simulate", limit=1, fast=True,
                            on_status=on_status)
        assert res["ok"] and res["accounts"] >= 3
        # every active account ran its first contact in parallel (limit=1)
        assert len(statuses) >= 3
        biz_ran = {biz for _, biz, _ in statuses}
        assert {"Dr Asha Clinic", "Glow and Go Salon", "Spice Junction"} <= biz_ran
        assert all(k == "SIM" for _, _, k in statuses)
        ours = {r["business_name"]: r["sent"] for r in res["results"]
                if r["business_name"] in {"Dr Asha Clinic", "Glow and Go Salon",
                                          "Spice Junction"}}
        assert all(v >= 1 for v in ours.values()), ours
    asyncio.run(_go())
