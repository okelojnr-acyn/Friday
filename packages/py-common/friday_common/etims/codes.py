"""KRA eTIMS standard codes, from the OSCU Specification Document v2.0
(kra.go.ke, section 4). KRA can add codes (/selectCodeList); these are
the ones Friday sends."""

# 4.1 Tax type (code class 04). Rates are KRA's defaults; the org's own
# rate for each code comes from Business settings > Tax.
TAX_TYPES = {
    "A": ("Exempt", 0),
    "B": ("16% VAT", 16),
    "C": ("Zero-rated", 0),
    "D": ("Non-VAT", 0),
    "E": ("8% VAT", 8),
}

# 4.3 Product type (code class 24).
PRODUCT_RAW_MATERIAL = "1"
PRODUCT_FINISHED = "2"
PRODUCT_SERVICE = "3"

# 4.9 Transaction type, 4.10 Sales receipt type, 4.12 Transaction progress.
SALES_TYPE_NORMAL = "N"
RECEIPT_SALE = "S"
RECEIPT_CREDIT_NOTE = "R"
SALES_STATUS_APPROVED = "02"

# 4.11 Payment method (code class 07), keyed by Friday's payment method.
PAYMENT_METHODS = {
    "cash": "01",
    "credit": "02",
    "split": "03",  # CASH/CREDIT
    "bank": "04",
    "card": "05",
    "mpesa": "06",  # mobile money
    "pesapal": "06",
    "airtel": "06",
}
PAYMENT_OTHER = "07"

# 4.17 Credit note reason (code class 32 in later specs); 06 = refund.
CREDIT_NOTE_REFUND = "06"

# 4.6 Packaging unit (code class 17): the ones a shop uses most.
PACKAGING_UNITS = {
    "NT": "Net (no packaging)",
    "BG": "Bag",
    "BX": "Box",
    "BQ": "Bottle",
    "CA": "Can",
    "CT": "Carton",
    "CR": "Crate",
    "DR": "Drum",
    "JR": "Jar",
    "JY": "Jerrycan",
    "PG": "Plate",
    "RL": "Reel",
    "RO": "Roll",
    "TY": "Tank",
    "OU": "Non-exterior packaging",
}

# 4.7 Unit of quantity (code class 10), complete.
QUANTITY_UNITS = {
    "4B": "Pair",
    "AV": "Cap",
    "BA": "Barrel",
    "BE": "Bundle",
    "BG": "Bag",
    "BL": "Block",
    "BLL": "Barrel (petroleum)",
    "BX": "Box",
    "CA": "Can",
    "CEL": "Cell",
    "CMT": "Centimetre",
    "CR": "Carat",
    "DR": "Drum",
    "DZ": "Dozen",
    "GLL": "Gallon",
    "GRM": "Gram",
    "GRO": "Gross",
    "KG": "Kilogram",
    "KTM": "Kilometre",
    "KWT": "Kilowatt",
    "L": "Litre",
    "LBR": "Pound",
    "LK": "Link",
    "LTR": "Litre",
    "M": "Metre",
    "M2": "Square metre",
    "M3": "Cubic metre",
    "MGM": "Milligram",
    "MTR": "Metre",
    "MWT": "Megawatt hour",
    "NO": "Number",
    "NX": "Part per thousand",
    "PA": "Packet",
    "PG": "Plate",
    "PR": "Pair",
    "RL": "Reel",
    "RO": "Roll",
    "SET": "Set",
    "ST": "Sheet",
    "TNE": "Tonne",
    "TU": "Tube",
    "U": "Pieces/item",
    "YRD": "Yard",
}

# 4.18 API response codes worth telling apart.
RESULT_OK = "000"
RESULT_NO_RESULT = "001"
RESULT_DUPLICATE = "994"

# Server addresses (OSCU spec 1.2).
SERVERS = {
    "sandbox": "https://etims-api-sbx.kra.go.ke/etims-api",
    "production": "https://etims-api.kra.go.ke/etims-api",
}

# Where a buyer checks a receipt: the QR code on an eTIMS receipt points
# here with tin + branch + receipt signature. Confirm against the sandbox
# before going live (production checks).
RECEIPT_CHECK = {
    "sandbox": "https://etims-sbx.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData?Data=",
    "production": "https://etims.kra.go.ke/common/link/etims/receipt/indexEtimsReceiptData?Data=",
}

# KRA's own PIN checker, for the manual path.
PIN_CHECKER_URL = "https://itax.kra.go.ke/KRA-Portal/pinChecker.htm"
