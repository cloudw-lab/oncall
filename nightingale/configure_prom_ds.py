import json
import requests

BASE = "http://localhost:17000"
USER = "root"
PASS = "root.2020"


def main():
    login = requests.post(
        f"{BASE}/api/n9e/auth/login",
        json={"username": USER, "password": PASS},
        timeout=8,
    )
    login.raise_for_status()
    token = login.json()["dat"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    list_resp = requests.post(
        f"{BASE}/api/n9e/datasource/list",
        headers=headers,
        json={},
        timeout=8,
    )
    list_resp.raise_for_status()
    rows = list_resp.json().get("data", [])

    ds_id = rows[0]["id"] if rows else 0
    payload = {
        "id": ds_id,
        "name": "prometheus-local",
        "identifier": "prometheus-local",
        "description": "Local Prometheus in docker compose",
        "plugin_id": 0,
        "plugin_type": "prometheus",
        "plugin_type_name": "Prometheus",
        "category": "metric",
        "cluster_name": "default",
        "settings": {},
        "status": "enabled",
        "http": {
            "url": "http://prometheus:9090",
            "timeout": 10000,
            "dial_timeout": 10000,
            "max_idle_conns_per_host": 100,
            "tls": {
                "skip_tls_verify": False,
                "ca_cert": "",
                "client_cert": "",
                "client_key": "",
                "client_key_password": "",
                "server_name": "",
                "min_version": "",
                "max_version": "",
            },
            "headers": [],
        },
        "auth": {
            "basic_auth": False,
            "basic_auth_user": "",
            "basic_auth_password": "",
        },
        "is_default": True,
        "force_save": True,
    }

    upsert = requests.post(
        f"{BASE}/api/n9e/datasource/upsert",
        headers=headers,
        json=payload,
        timeout=10,
    )
    upsert.raise_for_status()

    verify = requests.post(
        f"{BASE}/api/n9e/datasource/list",
        headers=headers,
        json={},
        timeout=8,
    )
    verify.raise_for_status()
    print(json.dumps(verify.json().get("data", []), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

