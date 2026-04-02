"""
Flood Severity Estimator – YOLOv8-seg ONNX, pure ONNX Runtime.

Pipeline
--------
1. Pre-process image to YOLOv8 input format (letterbox → normalise → CHW).
2. Run the ONNX session (exported from a 1-class "flood" YOLOv8-seg model).
3. Decode the two outputs:
     output0  [1, 37, 8400]  – boxes (cx,cy,w,h) + 1 class score + 32 mask coefs
     output1  [1, 32, 160, 160] – prototype masks
4. Filter by confidence, run vectorised NMS.
5. Build final binary flood mask in original-image coordinates.
6. Compute water coverage ratio inside the bottom ROI fraction.
7. Map coverage → severity label.

ONNX export command (run once, outside this service):
    yolo export model=best.pt format=onnx imgsz=640 simplify=True

Place the exported file at:
    ai_service/src/ai_service/models/yolo_flood_seg.onnx

Usage
-----
    from ai_service.core.flood_severity import FloodSeverityEstimator, SeverityConfig

    cfg = SeverityConfig()
    estimator = FloodSeverityEstimator(cfg)
    result = estimator.estimate(bgr_image_array)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import onnxruntime as ort

from ai_service.config import YOLO_SEVERITY_MODEL_PATH, YOLO_FLOOD_CLASS_ID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SeverityConfig:
    """Tunable parameters for the YOLO-ONNX flood severity estimator."""

    # ── Severity thresholds ──────────────────────────────────────────────────
    low_threshold: float = 0.05
    medium_threshold: float = 0.20
    high_threshold: float = 0.45

    # ── YOLO inference ────────────────────────────────────────────────────────
    yolo_conf: float = 0.25
    yolo_iou: float = 0.45
    yolo_imgsz: int = 640          # must match the imgsz used at export time
    flood_class_id: int = YOLO_FLOOD_CLASS_ID   # 0 for 1-class "flood" model


# ---------------------------------------------------------------------------
# Severity label
# ---------------------------------------------------------------------------

class Severity:
    NONE   = "None"
    LOW    = "Low"
    MEDIUM = "Medium"
    HIGH   = "High"

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
# Result (same public shape as before – backend API unchanged)
# ---------------------------------------------------------------------------

@dataclass
class EstimationResult:
    severity: str
    coverage_ratio: float
    raw_coverage_ratio: float          # same value – kept for API compat
    roi_mask: np.ndarray               # uint8 0/255, full image size
    water_mask: np.ndarray             # uint8 0/255, full image size
    wheels_detected: int               # always 0 – kept for API compat
    image_shape: Tuple[int, int, int]

    def __repr__(self) -> str:
        return (
            f"EstimationResult(severity={self.severity!r}, "
            f"coverage={self.coverage_ratio:.3f})"
        )


# ---------------------------------------------------------------------------
# Main estimator
# ---------------------------------------------------------------------------

class FloodSeverityEstimator:
    """
    Flood severity estimator powered by a YOLOv8-seg ONNX model.

    Parameters
    ----------
    config : SeverityConfig, optional
    model_path : str | Path | None, optional
        Override the default model path from config.
    """

    # Inference image size used by YOLOv8 letterboxing
    _IMGSZ = 640

    def __init__(
        self,
        config: Optional[SeverityConfig] = None,
        model_path: Optional[str | Path] = None,
    ) -> None:
        self.cfg = config or SeverityConfig()
        self._session = self._load_session(model_path)

    # ── public API ────────────────────────────────────────────────────────

    def estimate_from_path(self, image_path: str | Path) -> EstimationResult:
        img = cv2.imread(str(image_path))
        if img is None:
            raise FileNotFoundError(f"Cannot read image: {image_path}")
        return self.estimate(img)

    def estimate(self, bgr_image: np.ndarray) -> EstimationResult:
        """
        Run YOLOv8-seg ONNX inference on a BGR image, return EstimationResult.
        """
        cfg = self.cfg
        h, w = bgr_image.shape[:2]

        # 1. Pre-process
        blob, scale, (pad_x, pad_y) = self._letterbox(
            bgr_image, cfg.yolo_imgsz
        )

        # 2. Inference
        try:
            output0, output1 = self._session.run(
                None, {self._input_name: blob}
            )
        except Exception as exc:
            logger.error(f"YOLO ONNX inference error: {exc}", exc_info=True)
            return self._empty_result(h, w, bgr_image.shape)

        # output0: [1, 4+nc+32, num_boxes]  →  squeeze + transpose → [num_boxes, 37]
        # output1: [1, 32, mask_h, mask_w]
        preds = output0[0].T   # [8400, 37]
        protos = output1[0]    # [32, mask_h, mask_w]

        # 3. Decode + build full-image flood mask
        flood_mask = self._decode_masks(
            preds, protos, cfg, h, w, scale, pad_x, pad_y
        )

        # 4. Coverage calculation (Full image)
        roi_pixels = h * w
        coverage = float(np.count_nonzero(flood_mask)) / max(roi_pixels, 1)
        severity = Severity.from_coverage(coverage, cfg)

        roi_rect = np.full((h, w), 255, dtype=np.uint8)

        logger.info(
            f"Flood severity (YOLO-ONNX): {severity} | coverage={coverage:.3f}"
        )

        return EstimationResult(
            severity=severity,
            coverage_ratio=coverage,
            raw_coverage_ratio=coverage,
            roi_mask=roi_rect,
            water_mask=flood_mask,
            wheels_detected=0,
            image_shape=bgr_image.shape,
        )

    # ── private helpers ───────────────────────────────────────────────────

    def _load_session(self, model_path: Optional[str | Path]) -> ort.InferenceSession:
        """Load the ONNX model. Falls back to the config path if no override."""
        candidates: list[Path] = []
        if model_path is not None:
            candidates.append(Path(model_path))
        candidates.append(YOLO_SEVERITY_MODEL_PATH)

        for p in candidates:
            if p.exists():
                logger.info(f"Loading YOLO severity ONNX model from {p}")
                opts = ort.SessionOptions()
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                session = ort.InferenceSession(
                    str(p),
                    sess_options=opts,
                    providers=["CPUExecutionProvider"],
                )
                self._input_name = session.get_inputs()[0].name
                logger.info(
                    f"YOLO model loaded | input='{self._input_name}' "
                    f"outputs={[o.name for o in session.get_outputs()]}"
                )
                return session

        raise FileNotFoundError(
            f"YOLO severity ONNX model not found.\n"
            f"Tried: {[str(c) for c in candidates]}\n"
            f"Export with: yolo export model=best.pt format=onnx imgsz=640 simplify=True\n"
            f"Then place the .onnx file at: {YOLO_SEVERITY_MODEL_PATH}"
        )

    # ------------------------------------------------------------------
    # Image pre-processing (letterbox)
    # ------------------------------------------------------------------

    @staticmethod
    def _letterbox(
        img: np.ndarray, imgsz: int
    ) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        """
        Resize image to imgsz×imgsz with letterbox padding, return
        normalised [1,3,imgsz,imgsz] float32 blob plus the scale and
        (pad_x, pad_y) offsets in pixels (for mask back-projection).
        """
        h, w = img.shape[:2]
        scale = min(imgsz / h, imgsz / w)
        new_h, new_w = round(h * scale), round(w * scale)

        # Resize
        img_resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # Pad to imgsz×imgsz (grey fill)
        canvas = np.full((imgsz, imgsz, 3), 114, dtype=np.uint8)
        pad_x = (imgsz - new_w) // 2
        pad_y = (imgsz - new_h) // 2
        canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = img_resized

        # HWC BGR → CHW RGB, normalise to [0,1], add batch dim
        blob = canvas[:, :, ::-1].astype(np.float32) / 255.0   # BGR→RGB + norm
        blob = blob.transpose(2, 0, 1)[np.newaxis]              # -> [1,3,H,W]
        blob = np.ascontiguousarray(blob)

        return blob, scale, (pad_x, pad_y)

    # ------------------------------------------------------------------
    # Mask decoding (vectorised, no PyTorch)
    # ------------------------------------------------------------------

    def _decode_masks(
        self,
        preds: np.ndarray,          # [N, 4+nc+32]
        protos: np.ndarray,         # [32, mask_h, mask_w]
        cfg: SeverityConfig,
        orig_h: int,
        orig_w: int,
        scale: float,
        pad_x: int,
        pad_y: int,
    ) -> np.ndarray:
        """
        Decode YOLOv8-seg predictions into a binary flood mask.

        Returns a uint8 (0/255) mask of shape (orig_h, orig_w).
        """
        nc = 1  # number of classes (data.yaml nc=1)
        num_masks = 32

        flood_mask = np.zeros((orig_h, orig_w), dtype=np.uint8)

        # Extract components from preds [N, 4+nc+32]
        boxes_cx_cy_wh = preds[:, :4]            # cx, cy, w, h (in imgsz space)
        class_scores   = preds[:, 4:4 + nc]      # [N, nc]
        mask_coefs     = preds[:, 4 + nc:]       # [N, 32]

        # Keep only flood class (class 0) above confidence threshold
        flood_scores = class_scores[:, cfg.flood_class_id]
        conf_mask = flood_scores >= cfg.yolo_conf
        if not conf_mask.any():
            logger.debug("No flood detections above confidence threshold.")
            return flood_mask

        boxes_raw  = boxes_cx_cy_wh[conf_mask]
        scores_raw = flood_scores[conf_mask]
        coefs_raw  = mask_coefs[conf_mask]

        # Convert cx,cy,w,h → x1,y1,x2,y2 for NMS
        x1 = boxes_raw[:, 0] - boxes_raw[:, 2] / 2
        y1 = boxes_raw[:, 1] - boxes_raw[:, 3] / 2
        x2 = boxes_raw[:, 0] + boxes_raw[:, 2] / 2
        y2 = boxes_raw[:, 1] + boxes_raw[:, 3] / 2
        boxes_xyxy = np.stack([x1, y1, x2, y2], axis=1)

        keep = self._nms(boxes_xyxy, scores_raw, cfg.yolo_iou)
        if len(keep) == 0:
            return flood_mask

        boxes_xyxy = boxes_xyxy[keep]
        coefs_raw  = coefs_raw[keep]

        # Prototype masks shape: [32, mask_h, mask_w]
        mask_h, mask_w = protos.shape[1], protos.shape[2]
        protos_flat = protos.reshape(num_masks, -1)  # [32, mask_h*mask_w]

        for i in range(len(keep)):
            # Linear combination of prototypes
            single_mask = coefs_raw[i] @ protos_flat           # [mask_h*mask_w]
            single_mask = single_mask.reshape(mask_h, mask_w)
            # Sigmoid activation
            single_mask = 1.0 / (1.0 + np.exp(-single_mask))   # sigmoid

            # Scale box coords from imgsz to mask space
            mask_scale = mask_h / cfg.yolo_imgsz
            bx1 = int(boxes_xyxy[i, 0] * mask_scale)
            by1 = int(boxes_xyxy[i, 1] * mask_scale)
            bx2 = int(np.ceil(boxes_xyxy[i, 2] * mask_scale))
            by2 = int(np.ceil(boxes_xyxy[i, 3] * mask_scale))
            bx1, by1 = max(bx1, 0), max(by1, 0)
            bx2, by2 = min(bx2, mask_w), min(by2, mask_h)

            # Zero out pixels outside the bounding box
            crop = np.zeros_like(single_mask)
            crop[by1:by2, bx1:bx2] = single_mask[by1:by2, bx1:bx2]
            binary_mask = (crop > 0.5).astype(np.uint8) * 255  # [mask_h, mask_w]

            # Resize mask from mask_space → imgsz
            mask_imgsz = cv2.resize(
                binary_mask, (cfg.yolo_imgsz, cfg.yolo_imgsz),
                interpolation=cv2.INTER_LINEAR
            )

            # Remove letterbox padding, scale back to original image size
            # Letterbox: canvas[pad_y:pad_y+new_h, pad_x:pad_x+new_w]
            new_w = round(orig_w * scale)
            new_h = round(orig_h * scale)
            mask_content = mask_imgsz[
                pad_y: pad_y + new_h,
                pad_x: pad_x + new_w,
            ]
            mask_orig = cv2.resize(
                mask_content, (orig_w, orig_h),
                interpolation=cv2.INTER_LINEAR
            )
            binary_orig = (mask_orig > 127).astype(np.uint8) * 255

            flood_mask = cv2.bitwise_or(flood_mask, binary_orig)

        return flood_mask

    # ------------------------------------------------------------------
    # NMS (vectorised numpy)
    # ------------------------------------------------------------------

    @staticmethod
    def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
        """Simple greedy NMS. Returns indices of kept boxes."""
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
        order = scores.argsort()[::-1]
        keep: list[int] = []

        while order.size > 0:
            i = int(order[0])
            keep.append(i)
            if order.size == 1:
                break
            rest = order[1:]
            ix1 = np.maximum(x1[i], x1[rest])
            iy1 = np.maximum(y1[i], y1[rest])
            ix2 = np.minimum(x2[i], x2[rest])
            iy2 = np.minimum(y2[i], y2[rest])
            inter = np.maximum(0.0, ix2 - ix1) * np.maximum(0.0, iy2 - iy1)
            union = areas[i] + areas[rest] - inter
            iou = inter / np.maximum(union, 1e-6)
            order = rest[iou <= iou_thr]

        return keep

    # ------------------------------------------------------------------
    # Helper: empty result when inference fails
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_result(h: int, w: int, shape: tuple) -> EstimationResult:
        return EstimationResult(
            severity=Severity.NONE,
            coverage_ratio=0.0,
            raw_coverage_ratio=0.0,
            roi_mask=np.zeros((h, w), dtype=np.uint8),
            water_mask=np.zeros((h, w), dtype=np.uint8),
            wheels_detected=0,
            image_shape=shape,
        )
