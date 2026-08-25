from pharma_data.connectors.base import ManifestSourceAdapter
from pharma_data.contracts import DocumentType, LicenseStatus


class MarketDataAdapter(ManifestSourceAdapter):
    """接收交易所或合规数据商授权导出的行情文件，不抓取未授权行情。"""

    source_name = "authorized_mainland_market_data"
    adapter_name = "MarketDataAdapter"
    authority_tier = "A1"
    document_type = DocumentType.MARKET_DATA
    default_license_status = LicenseStatus.AUTHORIZED_RESTRICTED
    allowed_media_types = {
        "application/json",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
    }
