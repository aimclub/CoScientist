import base64
import logging
import re
from io import BytesIO

from PIL import Image

from ..general_utils import prompt_func
from ..general_utils import invoke_llm_with_retry
from ..prompts import cls_prompt, table_extraction_prompt, image_captioning_prompt
from ...domain.entities import ImageInfo

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _response_text(response) -> str:
    """Extract text from an AIMessage, including block-based content."""
    content = response.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts).strip()
    raise ValueError("LLM response contains no text")


def _has_non_empty_content(response) -> bool:
    try:
        return bool(_response_text(response))
    except (ValueError, AttributeError):
        return False


def pil_to_base64(image: Image.Image) -> str:
    try:
        buffered = BytesIO()
        image.save(buffered, format="JPEG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return img_str
    except Exception as e:
        logger.error(f"Failed to convert image to base64: {e}")
        raise e


def check_image_relevance(image_b64: str, llm) -> bool:
    try:
        query = [prompt_func({"text": cls_prompt, "image": [image_b64]})]
        decision = _response_text(invoke_llm_with_retry(
            llm,
            query,
            operation="check image relevance",
            response_validator=_has_non_empty_content,
        ))
        return decision != "False"
    except Exception as e:
        logger.error(f"Failed to check image relevance: {e}")
        raise


def try_extract_table(image_b64: str, llm) -> str | None:
    try:
        table_query = [prompt_func({"text": table_extraction_prompt, "image": [image_b64]})]
        res = _response_text(invoke_llm_with_retry(
            llm,
            table_query,
            operation="extract table from image",
            response_validator=_has_non_empty_content,
        ))

        if res != "No table":
            pattern = r'<table\b[^>]*>.*?</table>'
            match = re.search(pattern, res, re.DOTALL)
            if match:
                return match.group(0)
        return None
    except Exception as e:
        logger.error(f"Failed to determine table on image or extract table from image: {e}")
        raise e


def caption_image(
    image_info: ImageInfo,
    pil_image: Image.Image,
    llm
) -> ImageInfo:
    try:
        if not image_info.is_kept:
            return image_info

        image_b64 = pil_to_base64(pil_image)
        query = [prompt_func({"text": image_captioning_prompt, "image": [image_b64]})]
        caption = _response_text(invoke_llm_with_retry(
            llm,
            query,
            operation=f"caption image {image_info.id}",
            response_validator=_has_non_empty_content,
        ))
        image_info.caption = caption
        return image_info
    except Exception as e:
        logger.error(f"Failed to caption image: {e}")
        raise e
