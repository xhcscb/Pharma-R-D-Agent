from pharma_data.connectors.base import ManifestSourceAdapter
from pharma_data.contracts import DocumentType, LicenseStatus


class EarningsCallAdapter(ManifestSourceAdapter):
    source_name = "official_earnings_calls"
    adapter_name = "EarningsCallAdapter"
    authority_tier = "A2"
    document_type = DocumentType.EARNINGS_CALL
    default_license_status = LicenseStatus.PUBLIC
    allowed_media_types = {
        "application/pdf",
        "text/plain",
        "text/html",
        "audio/mpeg",
        "audio/wav",
        "audio/x-wav",
        "video/mp4",
    }
