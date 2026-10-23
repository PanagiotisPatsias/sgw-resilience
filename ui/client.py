import os

import httpx


class ApiClient:
    def __init__(self):
        self.url = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
        self.token = os.getenv("DEMO_API_TOKEN", "local-demo-token-change-before-deploy")

    def headers(self):
        return {"x-api-key": self.token}

    def request(self, method, path, **kwargs):
        with httpx.Client(timeout=90) as client:
            response = client.request(method, self.url + path, headers=self.headers(), **kwargs)
        if response.is_error:
            try:
                message = response.json().get("detail", "request failed")
            except ValueError:
                message = "request failed"
            raise RuntimeError(f"{response.status_code}: {message}")
        return response.json()
