import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class WalletOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    provider: str
    network: str
    address: str
    currency: str
    balance: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class PayoutRequest(BaseModel):
    to_address: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    amount: str = Field(min_length=1)
    network: str = Field(min_length=1)
    reason: str = ""


class CreditTransferSubmit(BaseModel):
    """A pacs.008-shaped message, passed through to the provider as-is --
    see AcynWalletProvider.submit_credit_transfer and the Acyn Wallet
    README's field reference (GrpHdr, CdtTrfTxInf, ...)."""

    message: dict


class TransactionOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    kind: str
    external_id: str
    status: str
    amount: str
    currency: str
    network: str
    to_address: str
    reason: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
