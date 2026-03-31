"""
Visualization helpers for the flood severity estimator.

Provides a side-by-side panel:
  [Original + ROI box + severity label]  |  [Water mask overlay]
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

from ai_service.core.flood_severity import EstimationResult, Severity


# ── Colour palette ───────────────────────────────────────────────────────────
_SEVERITY_COLOURS: dict[str, Tuple[int, int, int]] = {
    Severity.NONE:   (100, 220, 100),   # green
    Severity.LOW:    (0,   200, 255),   # amber-ish
    Severity.MEDIUM: (0,   140, 255),   # orange
    Severity.HIGH:   (40,  40,  220),   # red
}

_MASK_COLOUR: Tuple[int, int, int] = (255, 180, 0)   # cyan-blue overlay
_ROI_COLOUR:  Tuple[int, int, int] = (200, 200, 200) # light grey dashed box


def draw_result(
    bgr_image: np.ndarray,
    result: EstimationResult,
    panel_width: Optional[int] = None,
) -> np.ndarray:
    """
    Compose a two-panel visualisation.

    Left panel  : original image with ROI rectangle and severity label.
    Right panel : water mask overlay on the original.

    Parameters
    ----------
    bgr_image   : Source BGR image (original, full size).
    result      : EstimationResult from FloodSeverityEstimator.
    panel_width : Optional target width per panel. Defaults to original width.

    Returns
    -------
    np.ndarray – combined BGR image.
    """
    h, w = bgr_image.shape[:2]
    target_w = panel_width or w
    scale = target_w / w
    target_h = int(h * scale)
    resize = lambda img: cv2.resize(img, (target_w, target_h))  # noqa: E731

    left  = _draw_left_panel(bgr_image, result)
    right = _draw_right_panel(bgr_image, result)

    left  = resize(left)
    right = resize(right)

    return np.hstack([left, right])


def save_result(
    bgr_image: np.ndarray,
    result: EstimationResult,
    output_path: str | Path,
    panel_width: Optional[int] = None,
) -> Path:
    """Draw and save the visualisation to *output_path*."""
    panel = draw_result(bgr_image, result, panel_width)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), panel)
    return output_path


# ── Internal helpers ─────────────────────────────────────────────────────────

def _draw_left_panel(bgr_image: np.ndarray, result: EstimationResult) -> np.ndarray:
    """Original image with ROI rectangle and severity badge."""
    img = bgr_image.copy()
    h, w = img.shape[:2]

    # ROI rectangle
    roi_row = int(np.argmax(result.roi_mask.any(axis=1)))  # first non-zero row
    cv2.rectangle(img, (0, roi_row), (w - 1, h - 1), _ROI_COLOUR, 2)
    cv2.putText(
        img, "ROI",
        (6, roi_row - 6 if roi_row > 20 else roi_row + 20),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, _ROI_COLOUR, 1, cv2.LINE_AA
    )

    # Severity badge
    colour = _SEVERITY_COLOURS[result.severity]
    label  = f"Flood: {result.severity}"
    sub    = f"Coverage: {result.coverage_ratio:.1%}"

    _draw_badge(img, label, sub, colour, position="top-left")

    return img


def _draw_right_panel(bgr_image: np.ndarray, result: EstimationResult) -> np.ndarray:
    """Water mask overlaid on a darkened copy of the original image."""
    dark = (bgr_image * 0.45).astype(np.uint8)

    # Colour the detected water region
    mask_bool = result.water_mask > 0
    overlay = dark.copy()
    overlay[mask_bool] = _MASK_COLOUR

    # Blend with original for semi-transparent effect
    blended = cv2.addWeighted(dark, 0.5, overlay, 0.5, 0)

    # Contour around detected water for clarity
    contours, _ = cv2.findContours(
        result.water_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(blended, contours, -1, (255, 255, 255), 1)

    # Label
    cv2.putText(
        blended, "Water Mask",
        (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA
    )
    _draw_stats(blended, result)
    return blended


def _draw_badge(
    img: np.ndarray,
    line1: str,
    line2: str,
    colour: Tuple[int, int, int],
    position: str = "top-left",
) -> None:
    """Draw a semi-transparent coloured badge with two text lines."""
    h, w = img.shape[:2]
    font      = cv2.FONT_HERSHEY_SIMPLEX
    scale1, scale2 = 1.1, 0.65
    thick1, thick2 = 2, 1

    (tw1, th1), _ = cv2.getTextSize(line1, font, scale1, thick1)
    (tw2, th2), _ = cv2.getTextSize(line2, font, scale2, thick2)

    pad = 10
    box_w = max(tw1, tw2) + pad * 2
    box_h = th1 + th2 + pad * 3

    x0, y0 = pad, pad

    # Background rectangle (semi-transparent)
    sub = img[y0 : y0 + box_h, x0 : x0 + box_w]
    bg  = np.full_like(sub, colour, dtype=np.uint8)
    cv2.addWeighted(bg, 0.65, sub, 0.35, 0, sub)
    img[y0 : y0 + box_h, x0 : x0 + box_w] = sub

    # Border
    cv2.rectangle(img, (x0, y0), (x0 + box_w, y0 + box_h), colour, 2)

    # Text
    cv2.putText(img, line1, (x0 + pad, y0 + th1 + pad), font, scale1, (255, 255, 255), thick1, cv2.LINE_AA)
    cv2.putText(img, line2, (x0 + pad, y0 + th1 + th2 + pad * 2), font, scale2, (220, 220, 220), thick2, cv2.LINE_AA)


def _draw_stats(img: np.ndarray, result: EstimationResult) -> None:
    """Draw small stats text in the bottom-left of *img*."""
    h, w = img.shape[:2]
    font   = cv2.FONT_HERSHEY_SIMPLEX
    lines  = [
        f"raw coverage : {result.raw_coverage_ratio:.1%}",
        f"boosted      : {result.coverage_ratio:.1%}",
        f"wheels found : {result.wheels_detected}",
    ]
    y = h - 10 - (len(lines) - 1) * 22
    for line in lines:
        cv2.putText(img, line, (10, y), font, 0.52, (180, 255, 180), 1, cv2.LINE_AA)
        y += 22
