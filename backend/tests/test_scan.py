from io import BytesIO


def test_scan_upload_returns_candidates(client):
    image = BytesIO(b"not-a-real-image-but-valid-for-fallback")
    response = client.post(
        "/api/v1/scans",
        files={"file": ("carrefour-3560070791460.jpg", image, "image/jpeg")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scan_code"].startswith("scan_")
    assert body["status"] == "completed"
    assert body["barcode"] == "3560070791460"
    assert body["candidates"]
    assert body["candidates"][0]["confidence_score"] > 0.6
