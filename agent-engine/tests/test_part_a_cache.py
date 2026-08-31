"""
Part A.6 tests — Redis caching for business profile / catalog with
explicit invalidation on update. Runs fully hermetic via the
Cache's in-process fallback (no live Redis required).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cache import Cache, catalog_key, profile_key, stats_key  # noqa: E402


def _make_cache() -> Cache:
    c = Cache(redis_url="redis://127.0.0.1:1/0")  # unreachable -> fallback
    assert not c.is_redis  # using in-memory fallback in this environment
    return c


def test_cache_set_get_roundtrip_fallback():
    c = _make_cache()
    assert c.get("wa:cache:x") is None
    c.set("wa:cache:x", {"a": 1}, ttl=60)
    assert c.get("wa:cache:x") == {"a": 1}


def test_invalidate_prefix_removes_only_matching():
    c = _make_cache()
    c.set(catalog_key("BIZ1", "pizza"), [{"n": 1}], ttl=60)
    c.set(catalog_key("BIZ1"), [], ttl=60)
    c.set(profile_key("BIZ1"), {"name": "R"}, ttl=60)
    c.set(catalog_key("BIZ2", "pizza"), [{"n": 2}], ttl=60)

    deleted = c.invalidate_prefix(f"catalog:BIZ1:*")
    assert deleted == 2  # both BIZ1 catalog variants gone...
    assert c.get(catalog_key("BIZ1", "pizza")) is None
    assert c.get(catalog_key("BIZ1")) is None
    # ...while other keys are untouched
    assert c.get(profile_key("BIZ1")) == {"name": "R"}
    assert c.get(catalog_key("BIZ2", "pizza")) == [{"n": 2}]


def test_invalidate_business_clears_all_shapes():
    c = _make_cache()
    c.set(profile_key("B1"), {}, ttl=60)
    c.set(stats_key("B1"), {"total_orders": 3}, ttl=60)
    c.set(catalog_key("B1", "drinks"), [{}], ttl=60)
    c.set(catalog_key("B1"), [{}], ttl=60)
    c.set(profile_key("OTHER"), {}, ttl=60)

    n = c.invalidate_business("B1")
    assert n == 4
    assert c.get(profile_key("B1")) is None
    assert c.get(stats_key("B1")) is None
    assert c.get(catalog_key("B1", "drinks")) is None
    assert c.get(profile_key("OTHER")) == {}


def test_business_profile_catalog_invalidation_flow(tmp_path):
    """The actual BusinessManager mutation->invalidation contract."""
    from business_profiles import (
        BusinessManager,
        BusinessProfile,
        BusinessType,
        CatalogItem,
        Order,
    )
    from cache import cache as shared_cache

    # Never read/write the repo's real business_data.json during tests
    mgr = BusinessManager()
    mgr._DATA_FILE = str(tmp_path / "business_data_test.json")
    bid = "TEST_CACHE_BIZ_1"
    shared_cache._memory.clear()  # ensure clean fallback state for this test

    prof = BusinessProfile(id=bid, client_id=1, owner_id="o1",
                           business_type=BusinessType.RESTAURANT, name="T")
    created = mgr.create_profile(prof)
    assert shared_cache.get(profile_key(bid)) == created.to_dict()

    item = CatalogItem(id="it1", business_id=bid, category="main",
                       name="Paneer Tikka", price=180.0)
    mgr.add_catalog_item(bid, item)
    listed = mgr.get_catalog(bid)
    assert len(listed) == 1
    key = catalog_key(bid)
    assert shared_cache.get(key) == listed  # now cached

    # Mutation invalidates every cached listing...
    mgr.add_catalog_item(bid, CatalogItem(id="it2", business_id=bid,
                                          category="main", name="Dal Makhani",
                                          price=140.0))
    assert shared_cache.get(key) is None
    fresh = mgr.get_catalog(bid)
    assert len(fresh) == 2  # recomputed from source of truth

    # ...and update_profile invalidates profile + stats + catalogs
    mgr.create_order(bid, Order(id="ord1", business_id=bid, customer_phone="9999999999",
                                customer_name="A", items=[{"item_id": "it1", "qty": 1}],
                                total=100.0))
    # order mutation dropped any cached stats report
    assert shared_cache.get(stats_key(bid)) is None
    stats = mgr.get_business_stats(bid)
    assert stats["total_orders"] == 1
    assert shared_cache.get(stats_key(bid)) == stats

    mgr.update_order_status(bid, "ord1", "delivered")
    assert shared_cache.get(stats_key(bid)) is None  # explicitly invalidated
    assert mgr.get_business_stats(bid)["completed"] == 1

    mgr.update_profile(bid, name="Renamed")
    assert shared_cache.get(profile_key(bid)) is None
    assert shared_cache.get(stats_key(bid)) is None
    assert shared_cache.get(catalog_key(bid)) is None
    assert mgr.get_profile(bid).name == "Renamed"
