"""OCR engines behind one small interface, so the extractors do not care which runs.

- paddle: PaddleOCR 3.x, in-process (poetry install --with ocr)
- surya:  Surya 0.2x vision model on an inference server; reads Khmer (poetry install --with surya)

All engines run on our own machines; documents are never sent to an external service.
"""

import logging
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from PIL import Image

from app.core.config import Settings
from app.document_processing.errors import DocumentError, OcrUnavailableError

logger = logging.getLogger(__name__)


@dataclass
class OcrResult:
    text: str
    confidence: float | None  # mean score 0..1, None when nothing was recognized


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> OcrResult: ...


class DisabledOcrEngine:
    def recognize(self, image: Image.Image) -> OcrResult:
        raise OcrUnavailableError("OCR is disabled (OCR_ENGINE=none)")


class _LazyModelEngine:
    """Loads its model on first use and runs one image at a time.

    Subclasses implement `_load` (raise OcrUnavailableError when the engine cannot be
    used) and `_run`. Other errors become DocumentError("OCR failed"); only the
    exception type is logged, because messages may hold paths, URLs or document text.
    """

    def __init__(self) -> None:
        self._model = None
        self._load_error: OcrUnavailableError | None = None
        self._lock = threading.Lock()

    def _load(self):
        raise NotImplementedError

    def _run(self, model, image: Image.Image) -> OcrResult:
        raise NotImplementedError

    def recognize(self, image: Image.Image) -> OcrResult:
        with self._lock:
            if self._model is None:
                if self._load_error is not None:  # don't retry a failed load per page
                    raise self._load_error
                try:
                    self._model = self._load()
                except OcrUnavailableError as exc:
                    self._load_error = exc
                    raise
            try:
                return self._run(self._model, image)
            except DocumentError:
                raise
            except Exception as exc:
                logger.error("%s failed: %s", type(self).__name__, type(exc).__name__)
                raise DocumentError("OCR failed") from exc


class PaddleOcrEngine(_LazyModelEngine):
    """PaddleOCR 3.x. The model loads on first use (and downloads once if not cached)."""

    def __init__(self, language: str) -> None:
        super().__init__()
        self._language = language

    def _load(self):
        try:
            # Optional dependencies (numpy comes with them): poetry install --with ocr
            import numpy  # noqa: F401
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OcrUnavailableError(
                "PaddleOCR is not installed (poetry install --with ocr)"
            ) from exc
        logger.info("Loading PaddleOCR model (lang=%s)", self._language)
        try:
            return PaddleOCR(
                lang=self._language,
                # Scans are assumed upright; these extra models roughly double the cost.
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except Exception as exc:  # download or model errors; messages may hold paths/URLs
            logger.error("PaddleOCR model failed to load: %s", type(exc).__name__)
            raise OcrUnavailableError("OCR model could not be loaded") from exc

    def _run(self, model, image: Image.Image) -> OcrResult:
        import numpy as np

        # PaddleOCR expects BGR; the reversed view is copied to contiguous memory.
        bgr = np.ascontiguousarray(np.asarray(image.convert("RGB"))[:, :, ::-1])
        lines: list[str] = []
        scores: list[float] = []
        for res in model.predict(bgr):
            lines.extend(res["rec_texts"])
            scores.extend(float(s) for s in res["rec_scores"])
        confidence = sum(scores) / len(scores) if scores else None
        return OcrResult(text="\n".join(lines), confidence=confidence)


class SuryaOcrEngine(_LazyModelEngine):
    """Surya 0.2x: a vision-language OCR model (90+ languages, including Khmer).

    It runs on an inference server. With `inference_url` set, Surya uses that server
    (e.g. vLLM on the GPU server) and never starts one itself. Without it, Surya starts
    a local server on first use: llama.cpp on a Mac (`brew install llama.cpp`), which
    downloads the model once.
    """

    def __init__(self, inference_url: str | None, api_key: str) -> None:
        super().__init__()
        self._inference_url = inference_url
        self._api_key = api_key

    def _load(self):
        try:
            from surya.inference import SuryaInferenceManager
            from surya.recognition import RecognitionPredictor
            from surya.settings import settings as surya_settings
        except ImportError as exc:
            raise OcrUnavailableError(
                "Surya is not installed (poetry install --with surya)"
            ) from exc

        # Surya reads its own env vars, not our settings, so pass ours explicitly.
        method = None  # Surya picks: vllm on an NVIDIA GPU, llama.cpp otherwise
        if self._inference_url:
            self._check_server()
            surya_settings.SURYA_INFERENCE_URL = self._inference_url
            surya_settings.SURYA_INFERENCE_AUTOSTART = False
            surya_settings.VLLM_API_KEY = self._api_key
            method = "vllm"
        logger.info("Using Surya OCR (%s server)", "external" if self._inference_url else "local")
        try:
            return RecognitionPredictor(SuryaInferenceManager(method=method))
        except Exception as exc:
            logger.error("Surya failed to start: %s", type(exc).__name__)
            raise OcrUnavailableError("OCR model could not be loaded") from exc

    def _check_server(self) -> None:
        """Fail clearly on a wrong key or unreachable server. Surya itself turns request
        errors into an empty page, which would look like a blank document."""
        import httpx  # installed with Surya

        try:
            response = httpx.get(
                f"{self._inference_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            logger.error("Surya server unreachable: %s", type(exc).__name__)
            raise OcrUnavailableError("OCR server unreachable") from exc
        if response.status_code in (401, 403):
            raise OcrUnavailableError("OCR server rejected the API key (SURYA_INFERENCE_API_KEY)")
        if response.status_code != 200:
            raise OcrUnavailableError(f"OCR server returned HTTP {response.status_code}")

    def _run(self, model, image: Image.Image) -> OcrResult:
        from surya.common.blank import is_blank_region

        rgb = image.convert("RGB")
        page = model([rgb])[0]
        if not page.blocks and not is_blank_region(rgb):
            # Surya reports failed server requests as a page with no blocks.
            raise DocumentError("OCR returned no result for a non-blank page")
        blocks = [b for b in page.blocks if not b.skipped and not b.error]
        texts = [t for t in (html_to_text(b.html) for b in blocks) if t]
        scores = [b.confidence for b in blocks if b.confidence is not None]
        confidence = sum(scores) / len(scores) if scores else None
        return OcrResult(text="\n\n".join(texts), confidence=confidence)


_BLOCK_TAGS = ["p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6"]


def html_to_text(html: str) -> str:
    """Surya returns each block as HTML; keep line breaks and table rows readable."""
    from bs4 import BeautifulSoup  # installed with Surya

    soup = BeautifulSoup(html, "html.parser")
    for row in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        row.replace_with(" | ".join(cells) + "\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.append("\n")
    lines = (line.strip() for line in soup.get_text().splitlines())
    return "\n".join(line for line in lines if line)


@lru_cache
def _engine(name: str, language: str, surya_url: str | None, surya_key: str) -> OcrEngine:
    if name == "paddle":
        return PaddleOcrEngine(language)
    if name == "surya":
        return SuryaOcrEngine(surya_url, surya_key)
    return DisabledOcrEngine()


def get_ocr_engine(settings: Settings) -> OcrEngine:
    """Shared engine per configuration, so the model is loaded once per process.

    The engine handles one image at a time, so OCR jobs in one process run one after another.
    """
    return _engine(
        settings.ocr_engine,
        settings.ocr_language,
        settings.surya_inference_url,
        settings.surya_inference_api_key.get_secret_value(),
    )
