from io import BytesIO


def test_scan_upload_enqueues_pending_scan(client, monkeypatch):
    queued_scan_codes = []
    monkeypatch.setattr(
        "app.routers.scan.process_scan_job",
        lambda scan_code: queued_scan_codes.append(scan_code),
    )

    image = BytesIO(b"not-a-real-image-but-valid-for-fallback")
    response = client.post(
        "/api/v1/scans",
        files={"file": ("carrefour-3560070791460.jpg", image, "image/jpeg")},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["scan_code"].startswith("scan_")
    assert body["status"] == "pending"
    assert body["barcode"] is None
    assert body["candidates"] == []
    assert queued_scan_codes == [body["scan_code"]]
