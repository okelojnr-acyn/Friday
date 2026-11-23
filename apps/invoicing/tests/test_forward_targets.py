"""Forwarding only ever goes to public https addresses."""

from friday_common.public import forward_targets, public_https


async def test_only_public_https_addresses():
    assert await public_https("https://8.8.8.8/hook")
    for url in ["http://8.8.8.8/hook", "https://127.0.0.1/x", "https://10.0.0.5/x", "https://169.254.169.254/latest", "https://localhost/x", "https://[::1]/x", "ftp://x"]:
        assert not await public_https(url), url
    assert forward_targets({"forward_to": " https://a.example/h ,\nhttps://b.example/h "}) == ["https://a.example/h", "https://b.example/h"]
    assert forward_targets({}) == []
