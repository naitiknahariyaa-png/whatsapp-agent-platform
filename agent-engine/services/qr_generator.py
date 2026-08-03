"""
QR Code Generator — Dynamic Click-to-WhatsApp QR codes with tracking
"""
import json
import logging
import hashlib
import base64
from typing import Optional, Dict, Any, List
from datetime import datetime
from io import BytesIO

logger = logging.getLogger("qr_generator")


class QRCodeConfig:
    """Configuration for a dynamic QR code"""

    def __init__(self, phone_number: str, message: str = "",
                 utm_source: str = "qr", utm_medium: str = "print",
                 utm_campaign: str = "", custom_url: str = ""):
        self.qr_id = hashlib.md5(f"{phone_number}_{datetime.utcnow().timestamp()}".encode()).hexdigest()[:12]
        self.phone_number = phone_number
        self.message = message
        self.whatsapp_url = f"https://wa.me/{phone_number}" + (f"?text={message.replace(' ', '%20')}" if message else "")
        self.utm_source = utm_source
        self.utm_medium = utm_medium
        self.utm_campaign = utm_campaign
        self.custom_url = custom_url or self.whatsapp_url
        self.scan_count = 0
        self.conversion_count = 0
        self.is_active = True
        self.created_at = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict:
        return {
            "qr_id": self.qr_id,
            "phone_number": self.phone_number,
            "message": self.message,
            "whatsapp_url": self.whatsapp_url,
            "custom_url": self.custom_url,
            "utm_source": self.utm_source,
            "utm_medium": self.utm_medium,
            "utm_campaign": self.utm_campaign,
            "scan_count": self.scan_count,
            "conversion_count": self.conversion_count,
            "is_active": self.is_active,
            "created_at": self.created_at,
        }

    def generate_png(self, size: int = 400) -> Optional[bytes]:
        """Generate a QR code PNG image"""
        try:
            import qrcode
            from qrcode.image.styledpil import StyledPilImage
            from qrcode.image.styles.moduledrawers import RoundedModuleDrawer

            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=10,
                border=4,
            )
            qr.add_data(self.custom_url)
            qr.make(fit=True)

            img = qr.make_image(
                image_factory=StyledPilImage,
                module_drawer=RoundedModuleDrawer(),
                fill_color="#25D366",
                back_color="white",
            ).resize((size, size))

            buffer = BytesIO()
            img.save(buffer, format="PNG")
            return buffer.getvalue()
        except ImportError:
            logger.warning("qrcode library not installed. Install with: pip install qrcode[pil]")
            return None
        except Exception as e:
            logger.error(f"QR generation failed: {e}")
            return None

    def generate_svg(self) -> Optional[str]:
        """Generate a QR code as SVG string"""
        try:
            import qrcode
            import qrcode.image.svg
            qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H)
            qr.add_data(self.custom_url)
            qr.make(fit=True)

            factory = qrcode.image.svg.SvgPathImage
            img = qr.make_image(image_factory=factory)
            buffer = BytesIO()
            img.save(buffer)
            return buffer.getvalue().decode("utf-8")
        except ImportError:
            logger.warning("qrcode library not installed")
            return None
        except Exception as e:
            logger.error(f"QR SVG generation failed: {e}")
            return None

    def get_data_uri(self, size: int = 400) -> Optional[str]:
        """Get QR as a data URI (base64 PNG)"""
        png_bytes = self.generate_png(size)
        if png_bytes:
            b64 = base64.b64encode(png_bytes).decode("utf-8")
            return f"data:image/png;base64,{b64}"
        return None

    def record_scan(self):
        """Record a QR code scan"""
        self.scan_count += 1

    def record_conversion(self):
        """Record a conversion from this QR code"""
        self.conversion_count += 1

    def get_performance(self) -> Dict:
        return {
            "qr_id": self.qr_id,
            "scans": self.scan_count,
            "conversions": self.conversion_count,
            "conversion_rate": round(
                (self.conversion_count / max(self.scan_count, 1)) * 100, 1
            ),
        }


class QRCodeManager:
    """Manages dynamic QR codes"""

    def __init__(self):
        self.qr_codes: Dict[str, QRCodeConfig] = {}

    def create(self, phone_number: str, message: str = "",
               utm_source: str = "qr", utm_medium: str = "print",
               utm_campaign: str = "", custom_url: str = "") -> QRCodeConfig:
        """Create a new QR code"""
        config = QRCodeConfig(
            phone_number=phone_number,
            message=message,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign=utm_campaign,
            custom_url=custom_url,
        )
        self.qr_codes[config.qr_id] = config
        logger.info(f"[+] QR code created: {config.qr_id}")
        return config

    def get(self, qr_id: str) -> Optional[QRCodeConfig]:
        """Get QR code by ID"""
        return self.qr_codes.get(qr_id)

    def track_scan(self, qr_id: str) -> bool:
        """Track a scan event"""
        qr = self.get(qr_id)
        if qr:
            qr.record_scan()
            return True
        return False

    def track_conversion(self, qr_id: str) -> bool:
        """Track a conversion event"""
        qr = self.get(qr_id)
        if qr:
            qr.record_conversion()
            return True
        return False

    def redirect(self, qr_id: str) -> Optional[str]:
        """Get redirect URL for a QR code scan"""
        qr = self.get(qr_id)
        if qr and qr.is_active:
            qr.record_scan()
            return qr.custom_url
        return None

    def list(self) -> List[Dict]:
        """List all QR codes with performance"""
        return [qr.to_dict() for qr in self.qr_codes.values()]

    def get_stats(self) -> Dict:
        """Get aggregate QR code statistics"""
        total_scans = sum(qr.scan_count for qr in self.qr_codes.values())
        total_conversions = sum(qr.conversion_count for qr in self.qr_codes.values())
        return {
            "total_qr_codes": len(self.qr_codes),
            "total_scans": total_scans,
            "total_conversions": total_conversions,
            "overall_conversion_rate": round(
                (total_conversions / max(total_scans, 1)) * 100, 1
            ),
        }


# Global QR code manager
qr_manager = QRCodeManager()