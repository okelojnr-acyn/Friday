"""A client for KRA's eTIMS OSCU API (OSCU Specification Document v2.0).

Every call is a JSON POST to {server}/{function}. The taxpayer PIN,
branch ID and the CMC key (from device initialisation) go in the
request headers `tin`, `bhfId` and `cmcKey`, and the PIN and branch are
repeated in the body. Every reply has resultCd ("000" = succeeded),
resultMsg, resultDt and data.

Nothing here runs unless a server sets ETIMS_AUTOMATION=1 (production
checks); until then sales are filed by hand in the eTIMS portal.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from .codes import RESULT_NO_RESULT, RESULT_OK, SERVERS


class EtimsError(Exception):
    """KRA answered with a result code other than success, or could not
    be reached. `code` is KRA's resultCd ("" when unreachable)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code or 'unreachable'}: {message}")
        self.code = code
        self.message = message


@dataclass
class EtimsConfig:
    tin: str
    branch_id: str = "00"
    environment: str = "sandbox"
    cmc_key: str = ""
    device_serial: str = ""
    mode: str = "oscu"
    vscu_url: str = ""

    @classmethod
    def from_kernel(cls, cfg: dict) -> "EtimsConfig":
        return cls(
            tin=cfg.get("tax_pin", ""),
            branch_id=cfg.get("branch_id") or "00",
            environment=cfg.get("environment") or "sandbox",
            cmc_key=cfg.get("cmc_key", ""),
            device_serial=cfg.get("device_serial", ""),
            mode=cfg.get("mode") or "oscu",
            vscu_url=cfg.get("vscu_url", ""),
        )

    @property
    def base_url(self) -> str:
        # VSCU exposes the same functions on the business's own network.
        if self.mode == "vscu" and self.vscu_url:
            return self.vscu_url.rstrip("/")
        return SERVERS[self.environment]


class OscuClient:
    def __init__(self, config: EtimsConfig, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 20.0):
        self.config = config
        self._transport = transport
        self._timeout = timeout

    async def _call(self, function: str, body: dict[str, Any], *, allow_empty: bool = False) -> Any:
        c = self.config
        payload = {"tin": c.tin, "bhfId": c.branch_id, **body}
        headers = {"tin": c.tin, "bhfId": c.branch_id, "cmcKey": c.cmc_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as http:
                resp = await http.post(f"{c.base_url}/{function}", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise EtimsError("", f"could not reach eTIMS: {exc}") from exc
        try:
            out = resp.json()
        except ValueError as exc:
            raise EtimsError("", f"eTIMS answered HTTP {resp.status_code} without JSON") from exc
        code = str(out.get("resultCd", ""))
        if code == RESULT_OK or (allow_empty and code == RESULT_NO_RESULT):
            return out.get("data")
        raise EtimsError(code, str(out.get("resultMsg", "")))

    async def initialize(self) -> dict:
        """/selectInitOsdcInfo: activates the device; the reply carries
        the CMC key every other call needs."""
        data = await self._call("selectInitOsdcInfo", {"dvcSrlNo": self.config.device_serial})
        return (data or {}).get("info", {})

    async def lookup_customer(self, pin: str) -> dict | None:
        """/selectCustomer: the taxpayer registered to a PIN, or None."""
        data = await self._call("selectCustomer", {"custmTin": pin}, allow_empty=True)
        found = (data or {}).get("custList") or []
        return found[0] if found else None

    async def codes(self, last_request: str = "20180101000000") -> list[dict]:
        """/selectCodeList: standard codes changed since last_request."""
        data = await self._call("selectCodeList", {"lastReqDt": last_request}, allow_empty=True)
        return (data or {}).get("clsList") or []

    async def save_item(self, item: dict) -> None:
        """/saveItem: registers a product before it can be sold."""
        await self._call("saveItem", item)

    async def save_sale(self, sale: dict) -> dict:
        """/saveTrnsSalesOsdc: reports a sale or credit note; the reply
        carries the receipt numbers and signature for the receipt."""
        return await self._call("saveTrnsSalesOsdc", sale) or {}
