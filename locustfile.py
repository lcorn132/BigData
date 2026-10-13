"""Locust load test for recommendation and cross-sell endpoints.

Example:
  LOCUST_USER_IDS=557956487,123456 LOCUST_PRODUCT_IDS=5826000,5143 \
    locust -f locustfile.py --host http://127.0.0.1:8000 \
    -u 200 -r 20 -t 3m --headless --csv=results/run --html=results/report.html
"""

import os
import random

from locust import HttpUser, between, task


def _env_values(name: str, default: str) -> list[str]:
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


USER_IDS = _env_values("LOCUST_USER_IDS", "557956487")
PRODUCT_IDS = _env_values("LOCUST_PRODUCT_IDS", "5826000")


class RecommendationUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task(3)
    def personalized_recommendations(self):
        user_id = random.choice(USER_IDS)
        self.client.get(
            f"/api/v1/recommendations/{user_id}?limit=5",
            name="GET /api/v1/recommendations/{user_id}",
        )

    @task(2)
    def cross_sell(self):
        product_id = random.choice(PRODUCT_IDS)
        self.client.get(
            f"/api/v1/cross-sell/{product_id}?limit=3",
            name="GET /api/v1/cross-sell/{product_id}",
        )
