"""Product photos and variants (owner, 2026-11-16)."""

from dataclasses import replace

from friday_common.testing import make_principal

WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8 " + b"\x00" * 20


async def test_a_photo_is_stored_served_and_removed(client):
    p = (await client.post("/products", json={"name": "Office Chair", "price_cents": 700000})).json()
    assert p["image_sha"] == ""
    up = await client.put(f"/products/{p['id']}/image", content=WEBP, headers={"Content-Type": "image/webp"})
    assert up.status_code == 200, up.text
    sha = up.json()["image_sha"]
    assert len(sha) == 16
    got = await client.get(f"/products/{p['id']}/image?v={sha}")
    assert got.status_code == 200 and got.content == WEBP
    assert got.headers["content-type"] == "image/webp" and "immutable" in got.headers["cache-control"]
    gone = await client.delete(f"/products/{p['id']}/image")
    assert gone.json()["image_sha"] == ""
    assert (await client.get(f"/products/{p['id']}/image")).status_code == 404


async def test_photos_are_checked(client):
    p = (await client.post("/products", json={"name": "Lamp"})).json()
    bad_type = await client.put(f"/products/{p['id']}/image", content=b"GIF89a", headers={"Content-Type": "image/gif"})
    assert bad_type.status_code == 415
    too_big = await client.put(f"/products/{p['id']}/image", content=b"x" * (401 * 1024), headers={"Content-Type": "image/jpeg"})
    assert too_big.status_code == 413


async def test_another_orgs_photo_is_not_reachable(client, as_principal, principal):
    p = (await client.post("/products", json={"name": "Desk"})).json()
    await client.put(f"/products/{p['id']}/image", content=WEBP, headers={"Content-Type": "image/webp"})
    as_principal(make_principal())
    assert (await client.get(f"/products/{p['id']}/image")).status_code == 404
    as_principal(principal)


async def test_variants_belong_to_one_main_product(client, as_principal, principal):
    sugar = (await client.post("/products", json={"name": "Sugar", "category": "Groceries"})).json()
    kg1 = (await client.post("/products", json={"name": "Sugar 1kg", "variant_of": sugar["id"], "variant_name": "1 kg", "price_cents": 16500})).json()
    assert kg1["variant_of"] == sugar["id"] and kg1["variant_name"] == "1 kg"
    # No variants of variants, and a product with variants can't become one.
    nested = await client.post("/products", json={"name": "x", "variant_of": kg1["id"]})
    assert nested.status_code == 422
    other = (await client.post("/products", json={"name": "Salt"})).json()
    assert (await client.patch(f"/products/{sugar['id']}", json={"variant_of": other["id"]})).status_code == 422
    assert (await client.patch(f"/products/{kg1['id']}", json={"variant_of": kg1["id"]})).status_code == 422
    # Another org's product can't be the main one.
    as_principal(make_principal())
    theirs = await client.post("/products", json={"name": "y", "variant_of": sugar["id"]})
    assert theirs.status_code == 422
    as_principal(principal)


async def test_viewers_cannot_change_photos(client, as_principal, principal):
    p = (await client.post("/products", json={"name": "Bin"})).json()
    as_principal(replace(principal, role="viewer"))
    r = await client.put(f"/products/{p['id']}/image", content=WEBP, headers={"Content-Type": "image/webp"})
    assert r.status_code == 403
    as_principal(principal)
