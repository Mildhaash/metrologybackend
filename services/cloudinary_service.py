# services/cloudinary_service.py

import os
import logging
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Configure Cloudinary from environment variables
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
)

FOLDER = "metrology-scans"


def is_configured() -> bool:
    """Check if Cloudinary credentials are configured."""
    return all([
        os.getenv("CLOUDINARY_CLOUD_NAME"),
        os.getenv("CLOUDINARY_API_KEY"),
        os.getenv("CLOUDINARY_API_SECRET"),
    ])


def upload_image(file_path: str, scan_id: str = None) -> str | None:
    """
    Upload an image file to Cloudinary.
    Returns the secure URL on success, None on failure.
    """
    if not is_configured():
        logger.warning("Cloudinary not configured, skipping upload")
        return None

    try:
        public_id = f"{FOLDER}/{scan_id}" if scan_id else FOLDER
        result = cloudinary.uploader.upload(
            file_path,
            public_id=public_id,
            folder=FOLDER,
            resource_type="image",
            format="jpg",
        )
        return result.get("secure_url")
    except Exception as e:
        logger.error(f"Cloudinary upload failed: {e}")
        return None


def upload_base64(base64_data: str, scan_id: str = None) -> str | None:
    """
    Upload a base64-encoded image to Cloudinary.
    Returns the secure URL on success, None on failure.
    """
    if not is_configured():
        logger.warning("Cloudinary not configured, skipping upload")
        return None

    try:
        # Add data URI prefix if not present
        if not base64_data.startswith("data:"):
            base64_data = f"data:image/jpeg;base64,{base64_data}"

        result = cloudinary.uploader.upload(
            base64_data,
            folder=FOLDER,
            resource_type="image",
            format="jpg",
        )
        return result.get("secure_url")
    except Exception as e:
        logger.error(f"Cloudinary base64 upload failed: {e}")
        return None


def delete_image(public_id: str) -> bool:
    """
    Delete an image from Cloudinary.
    Returns True on success, False on failure.
    """
    if not is_configured():
        return False

    try:
        result = cloudinary.uploader.destroy(public_id)
        return result.get("result") == "ok"
    except Exception as e:
        logger.error(f"Cloudinary delete failed: {e}")
        return False
