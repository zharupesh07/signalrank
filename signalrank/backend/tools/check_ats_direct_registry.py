from __future__ import annotations

import asyncio
import json

import httpx

from batch.sources import ats_direct


async def main() -> None:
    rows = []
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for company in ats_direct.active_companies():
            rows.append(await ats_direct.probe_company(client, company))

    bad = [row for row in rows if row["status"] != 200]
    print(
        json.dumps(
            {
                "active": len(rows),
                "healthy": len(rows) - len(bad),
                "unhealthy": len(bad),
                "disabled": ats_direct._DISABLED_ATS_COMPANIES,
                "bad_rows": bad,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
