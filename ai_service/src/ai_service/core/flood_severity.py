"""
Flood Severity Estimator – heuristic-based, OpenCV only.

Pipeline
--------
1. Focus on the bottom region of the frame (configurable fraction).
2. Convert to HSV and apply colour + saturation masks that capture
   typical water/wet-road tones (blue family, grey-reflective tints).
3. Optionally run a Canny-texture pass to suppress non-flat surfaces.
4. Optionally detect car-wheel-sized circles (Hough) as reference objects
   to add a contextual confidence boost.
5. Compute water coverage ratio = water_pixels / ROI_pixels.
6. Map coverage to severity with tunable thresholds.

Usage
-----
    from ai_service.core.flood_severity import FloodSeverityEstimator, SeverityConfig

    cfg = SeverityConfig()          # tweak thresholds here
    estimator = FloodSeverityEstimator(cfg)
    result = estimator.estimate("path/to/frame.jpg")
    print(result)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration dataclass  (easy to tune / serialise)
# ---------------------------------------------------------------------------

@dataclass
class SeverityConfig:
    """All tunable parameters for the flood severity estimator."""

    # ── ROI ─────────────────────────────────────────────────────────────────
    roi_bottom_fraction: float = 0.50
    """Proportion of image height used as the Region Of Interest (bottom)."""

    # ── Water colour masks (HSV) ─────────────────────────────────────────────
    # Blue-water band
    water_hue_low: int = 85
    water_hue_high: int = 135
    water_sat_min: int = 30
    water_val_min: int = 40

    # Grey/reflective-wet-road band (low saturation, mid-high value)
    wet_sat_max: int = 50
    wet_val_min: int = 80
    wet_val_max: int = 220

    # ── Texture gate ────────────────────────────────────────────────────────
    use_texture_gate: bool = True
    """If True, suppress high-edge areas (vegetation, car surfaces, etc.)."""
    texture_canny_low: int = 40
    texture_canny_high: int = 120
    texture_dilation_px: int = 5
    texture_edge_density_thresh: float = 0.25
    """Reject a patch if edge-pixel density exceeds this value."""

    # ── Severity thresholds (water coverage ratio) ───────────────────────────
    low_threshold: float = 0.08
    """Coverage ratio above which severity becomes LOW."""
    medium_threshold: float = 0.25
    """Coverage ratio above which severity becomes MEDIUM."""
    high_threshold: float = 0.50
    """Coverage ratio above which severity becomes HIGH."""

    # ── Reference-object detection (car wheels) ──────────────────────────────
    use_wheel_detection: bool = True
    """Attempt Hough circle detection to find car wheels as reference objects."""
    wheel_dp: float = 1.2
    wheel_min_dist_ratio: float = 0.08
    """min_dist = image_width * this value."""
    wheel_param1: int = 60
    wheel_param2: int = 30
    wheel_min_radius_ratio: float = 0.02
    wheel_max_radius_ratio: float = 0.12
    wheel_boost: float = 0.05
    """Coverage ratio bonus when wheels sitting near water are detected."""

    # ── Morphology ───────────────────────────────────────────────────────────
    morph_open_px: int = 5
    """Kernel size for morphological opening (noise removal)."""
    morph_close_px: int = 15
    """Kernel size for morphological closing (hole filling)."""


# ---------------------------------------------------------------------------
# Severity label
# ---------------------------------------------------------------------------

class Severity:
    NONE = "None"
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"

    _ORDER = [NONE, LOW, MEDIUM, HIGH]

    @classmethod
    def from_coverage(cls, ratio: float, cfg: SeverityConfig) -> str:
        if ratio >= cfg.high_threshold:
            return cls.HIGH
        if ratio >= cfg.medium_threshold:
            return cls.MEDIUM
        if ratio >= cfg.low_threshold:
            return cls.LOW
        return cls.NONE


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EstimationResult:
    severity: str
    coverage_ratio: float
    raw_coverage_ratio: float   # before wheel boost
    roi_mask: np.ndarray        # binary mask of full ROI
    water_mask: np.ndarray      # binary water mask (same size as full image)
    wheels_detected: int
    image_shape: Tuple[int, int, int]

    def __repr__(self) -> str:
        return (
            f"EstimationResult(severity={self.severity!r}, "
            f"coverage={self.coverage_ratio:.3f}, "
            f"wheels={self.wheels_detected})"
        )


# ---------------------------------------------------------------------------
# Main estimator
# ---------------------------------------------------------------------------

class FloodSeverityEstimator:
    """
    Lightweight, real-time flood severity estimator.

    Parameters
    ----------
    config : SeverityConfig
        Tunable parameters. Pass a custom config to override defaults.
    """

    def __init__(self, config: Optional[SeverityConfig] = None) -> None:
        self.cfg = config or SeverityConfig()

    # ── public API ────────────────────────────────────────────────────────

    def estimate_from_path(self, image_path: str | Path) -> EstimationResult:
        """Load an image from disk and estimate flood severity."""
        img = cv2.imread(str(image_path))
        if img is None:
            raise FileNotFoundError(f"Cannot read image: {image_path}")
        return self.estimate(img)

    def estimate(self, bgr_image: np.ndarray) -> EstimationResult:
        """
        Estimate flood severity from a BGR image array.

        Parameters
        ----------
        bgr_image : np.ndarray
            Image in OpenCV BGR format, shape (H, W, 3).

        Returns
        -------
        EstimationResult
        """
        cfg = self.cfg
        h, w = bgr_image.shape[:2]

        # ── 1. Extract bottom ROI ────────────────────────────────────────
        roi_top = int(h * (1.0 - cfg.roi_bottom_fraction))
        roi_bgr = bgr_image[roi_top:, :]
        roi_pixels = roi_bgr.shape[0] * roi_bgr.shape[1]

        # ── 2. Build water mask ─────────────────────────────────────────
        water_mask_roi = self._build_water_mask(roi_bgr)

        # Texture gate: suppress complex-texture regions
        if cfg.use_texture_gate:
            water_mask_roi = self._apply_texture_gate(roi_bgr, water_mask_roi)

        # Morphological clean-up
        water_mask_roi = self._morph_clean(water_mask_roi)

        # ── 3. Coverage ratio ───────────────────────────────────────────
        raw_coverage = float(np.count_nonzero(water_mask_roi)) / roi_pixels

        # ── 4. Wheel boost ──────────────────────────────────────────────
        wheels = 0
        coverage = raw_coverage
        if cfg.use_wheel_detection:
            wheels = self._detect_wheels(roi_bgr, water_mask_roi)
            if wheels > 0:
                # Wheels near water → evidence of partial submersion
                coverage = min(1.0, raw_coverage + cfg.wheel_boost)
                logger.debug(f"Wheel boost applied: {raw_coverage:.3f} → {coverage:.3f}")

        # ── 5. Severity classification ──────────────────────────────────
        severity = Severity.from_coverage(coverage, cfg)

        # ── 6. Reconstruct full-image mask for visualisation ────────────
        full_mask = np.zeros((h, w), dtype=np.uint8)
        full_mask[roi_top:, :] = water_mask_roi

        # ROI rectangle mask (for overlay)
        roi_rect = np.zeros((h, w), dtype=np.uint8)
        roi_rect[roi_top:, :] = 255

        logger.info(
            f"Flood severity: {severity} | coverage={coverage:.3f} "
            f"(raw={raw_coverage:.3f}) | wheels={wheels}"
        )

        return EstimationResult(
            severity=severity,
            coverage_ratio=coverage,
            raw_coverage_ratio=raw_coverage,
            roi_mask=roi_rect,
            water_mask=full_mask,
            wheels_detected=wheels,
            image_shape=bgr_image.shape,
        )

    # ── private helpers ───────────────────────────────────────────────────

    def _build_water_mask(self, roi_bgr: np.ndarray) -> np.ndarray:
        """Combine blue-water and wet-road HSV masks."""
        cfg = self.cfg
        hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)

        # Mask 1: blue-ish water
        lower_blue = np.array([cfg.water_hue_low, cfg.water_sat_min, cfg.water_val_min])
        upper_blue = np.array([cfg.water_hue_high, 255, 255])
        mask_blue = cv2.inRange(hsv, lower_blue, upper_blue)

        # Mask 2: grey reflective wet road (very low saturation)
        lower_wet = np.array([0, 0, cfg.wet_val_min])
        upper_wet = np.array([180, cfg.wet_sat_max, cfg.wet_val_max])
        mask_wet = cv2.inRange(hsv, lower_wet, upper_wet)

        # Combine
        combined = cv2.bitwise_or(mask_blue, mask_wet)
        return combined

    def _apply_texture_gate(
        self, roi_bgr: np.ndarray, mask: np.ndarray
    ) -> np.ndarray:
        """
        Zero out mask regions where edge density is too high
        (likely non-water surfaces such as vehicles, vegetation).
        """
        cfg = self.cfg
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, cfg.texture_canny_low, cfg.texture_canny_high)

        # Dilate edges to create exclusion zones
        k = cfg.texture_dilation_px
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
        edges_dilated = cv2.dilate(edges, kernel)

        # Compute local edge density using a box filter
        edge_float = edges_dilated.astype(np.float32) / 255.0
        density = cv2.boxFilter(edge_float, -1, (51, 51))  # ~50 px window

        high_texture = (density > cfg.texture_edge_density_thresh).astype(np.uint8) * 255
        # Remove high-texture pixels from mask
        return cv2.bitwise_and(mask, cv2.bitwise_not(high_texture))

    def _morph_clean(self, mask: np.ndarray) -> np.ndarray:
        """Remove noise (open) then fill gaps (close)."""
        cfg = self.cfg
        k_open = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (cfg.morph_open_px, cfg.morph_open_px)
        )
        k_close = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (cfg.morph_close_px, cfg.morph_close_px)
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k_open)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k_close)
        return mask

    def _detect_wheels(
        self, roi_bgr: np.ndarray, water_mask_roi: np.ndarray
    ) -> int:
        """
        Detect dark circular blobs (car wheels) and check if they overlap
        or are adjacent to the water mask.  Returns the number of qualifying
        wheel candidates found.
        """
        cfg = self.cfg
        h, w = roi_bgr.shape[:2]
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (9, 9), 2)

        min_r = int(w * cfg.wheel_min_radius_ratio)
        max_r = int(w * cfg.wheel_max_radius_ratio)
        min_dist = int(w * cfg.wheel_min_dist_ratio)

        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=cfg.wheel_dp,
            minDist=min_dist,
            param1=cfg.wheel_param1,
            param2=cfg.wheel_param2,
            minRadius=min_r,
            maxRadius=max_r,
        )

        if circles is None:
            return 0

        circles = np.round(circles[0]).astype(int)
        count = 0
        for cx, cy, r in circles:
            # Check that the circle centre is dark (wheel-like)
            roi_mask_circle = np.zeros((h, w), dtype=np.uint8)
            cv2.circle(roi_mask_circle, (cx, cy), r, 255, -1)
            mean_val = cv2.mean(gray, mask=roi_mask_circle)[0]
            if mean_val > 120:
                continue  # too bright → likely not a tyre

            # Check proximity to water mask
            expanded = cv2.dilate(roi_mask_circle, np.ones((r, r), np.uint8))
            overlap = cv2.bitwise_and(expanded, water_mask_roi)
            if np.count_nonzero(overlap) > 0:
                count += 1
                logger.debug(f"Wheel candidate near water: centre=({cx},{cy}) r={r}")

        return count
