import hashlib
import hmac
import json
from urllib.parse import urlencode

from fczhk.db import now


def signed_data(token, age=0, user_id=102, username=None):
    values = {
        "auth_date": str(int(now().timestamp()) - age),
        "query_id": "abc",
        "user": json.dumps({"id": user_id, "first_name": "Игрок", "username": username}),
    }
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(
        secret, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(values)
