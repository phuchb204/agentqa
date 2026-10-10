from __future__ import annotations

import asyncio
import json
import os
import sys

from agentqa.platform.security.egress import AllowedEndpoint, EgressPolicy
from agentqa.platform.security.proxy import EgressProxy


def _load_endpoints() -> list[AllowedEndpoint]:
    raw = os.environ.get("AGENTQA_EGRESS_ALLOW", "[]")
    entries = json.loads(raw)
    return [
        AllowedEndpoint(
            host=str(entry["host"]),
            port=int(entry["port"]),
            addresses=tuple(str(item) for item in entry.get("addresses", ("127.0.0.1",))),
        )
        for entry in entries
    ]


async def main() -> None:
    policy = EgressPolicy(_load_endpoints())
    proxy = EgressProxy(policy, host="0.0.0.0", port=int(os.environ.get("AGENTQA_EGRESS_PORT", "8899")))
    url = await proxy.start()
    print(json.dumps({"egress_proxy": url}), flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
