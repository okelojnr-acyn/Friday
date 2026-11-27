"""The online shop's catalogue: a shop session sees what a shopper may
see, and nothing else; staff sessions can't use it."""

from friday_common import Principal

WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8 " + b"\x00" * 20  # as in test_product_images_variants


def as_shop(principal):
    return Principal(user_id="shop:key-1", org_id=principal.org_id, role="shop", email="", via="shop")


async def test_the_shop_sees_prices_and_stock_never_costs(client, principal, as_principal):
    tea = (await client.post("/products", json={"name": "Tea 500g", "category": "Drinks", "price_cents": 35000, "cost_cents": 20000})).json()
    await client.post("/products", json={"name": "Free sample", "price_cents": 0})
    delivery = (await client.post("/products", json={"name": "Delivery", "kind": "service", "price_cents": 20000})).json()
    await client.put(f"/products/{tea['id']}/image", content=WEBP, headers={"Content-Type": "image/webp"})

    # Staff sessions can't use the shop's routes.
    assert (await client.get("/shop/catalog")).status_code == 403

    as_principal(as_shop(principal))
    items = {p["name"]: p for p in (await client.get("/shop/catalog")).json()}
    assert set(items) == {"Tea 500g", "Delivery"}, "only priced products"
    t = items["Tea 500g"]
    assert t["price_cents"] == 35000 and t["category"] == "Drinks" and t["in_stock"] is False
    assert t["image_sha"], "photo listed"
    assert items["Delivery"]["in_stock"] is True, "services are always available"
    for p in items.values():
        assert not {"cost_cents", "on_hand_qty", "sku", "barcode", "reorder_point"} & set(p), p

    photo = await client.get(f"/shop/products/{tea['id']}/image")
    assert photo.status_code == 200 and photo.content == WEBP
    assert (await client.get(f"/shop/products/{delivery['id']}/image")).status_code == 404

    # Other routes refuse a shop session.
    assert (await client.get("/products")).status_code in (401, 403)
