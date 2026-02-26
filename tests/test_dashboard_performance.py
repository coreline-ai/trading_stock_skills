from __future__ import annotations

import statistics
import time


def test_top_picks_p95_under_300ms(client):
    durations_ms: list[float] = []

    for _ in range(80):
        start = time.perf_counter()
        response = client.get("/api/v1/dashboard/top-picks", params={"limit": 5})
        end = time.perf_counter()

        assert response.status_code == 200
        durations_ms.append((end - start) * 1000)

    p95 = statistics.quantiles(durations_ms, n=100)[94]
    assert p95 < 300, f"Expected p95 < 300ms, got {p95:.2f}ms"
