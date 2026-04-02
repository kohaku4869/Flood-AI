#!/usr/bin/env python
"""
Flood Severity Demo
===================
Standalone script to test the heuristic flood severity pipeline on a single
image or a directory of images.

Usage
-----
    # Single image – show result in a window
    python flood_detect_demo.py path/to/image.jpg

    # Single image – save result
    python flood_detect_demo.py path/to/image.jpg --save output.png

    # Directory – process all images and save results
    python flood_detect_demo.py path/to/images/ --save results/

    # Tune thresholds inline
    python flood_detect_demo.py image.jpg \\
        --roi 0.5 \\
        --low 0.08 --medium 0.25 --high 0.50 \\
        --no-wheel

Dependencies
------------
    pip install opencv-python numpy
"""

import argparse
import sys
import time
from pathlib import Path

import cv2

# ── Allow running from both the package root and project root ──────────────
_SRC = Path(__file__).parent / "src"
if _SRC.exists():
    sys.path.insert(0, str(_SRC))

from ai_service.core.flood_severity import FloodSeverityEstimator, SeverityConfig
from ai_service.core.flood_visualizer import draw_result, save_result

# ── Supported extensions ───────────────────────────────────────────────────
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


def build_config(args: argparse.Namespace) -> SeverityConfig:
    """Construct a SeverityConfig from CLI arguments."""
    return SeverityConfig(
        low_threshold=args.low,
        medium_threshold=args.medium,
        high_threshold=args.high,
    )


def process_image(
    estimator: FloodSeverityEstimator,
    image_path: Path,
    save_path: Path | None,
    display: bool,
    panel_width: int,
) -> None:
    """Run the pipeline on a single image."""
    bgr = cv2.imread(str(image_path))
    if bgr is None:
        print(f"[WARN] Cannot read: {image_path}")
        return

    t0 = time.perf_counter()
    result = estimator.estimate(bgr)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(
        f"  {image_path.name:<40} "
        f"severity={result.severity:<8} "
        f"coverage={result.coverage_ratio:.1%}  "
        f"({elapsed_ms:.1f} ms)"
    )

    panel = draw_result(bgr, result, panel_width=panel_width)

    if save_path is not None:
        sp = save_path / image_path.name if save_path.is_dir() else save_path
        cv2.imwrite(str(sp), panel)
        print(f"    → saved: {sp}")

    if display:
        cv2.imshow("Flood Severity Estimator", panel)
        key = cv2.waitKey(0 if save_path is None else 800)
        if key == ord("q"):
            cv2.destroyAllWindows()
            sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Heuristic flood severity estimation from traffic camera images."
    )
    parser.add_argument("input", help="Path to an image file or directory.")
    parser.add_argument("--save", metavar="PATH", help="Save visualisation to file or directory.")
    parser.add_argument("--no-display", action="store_true", help="Skip OpenCV window display.")
    parser.add_argument("--panel-width", type=int, default=640, help="Width of each side-by-side panel (px).")

    # Threshold tuning
    parser.add_argument("--low",    type=float, default=0.05, help="Coverage threshold for LOW severity.")
    parser.add_argument("--medium", type=float, default=0.20, help="Coverage threshold for MEDIUM severity.")
    parser.add_argument("--high",   type=float, default=0.45, help="Coverage threshold for HIGH severity.")

    # Feature toggles
    parser.add_argument("--no-wheel",   action="store_true", help="Disable wheel/reference-object detection.")
    parser.add_argument("--no-texture", action="store_true", help="Disable texture gate (Canny suppression).")

    args = parser.parse_args()

    cfg       = build_config(args)
    estimator = FloodSeverityEstimator(cfg)
    input_p   = Path(args.input)
    save_p    = Path(args.save) if args.save else None
    display   = not args.no_display

    if save_p and save_p.suffix == "":
        save_p.mkdir(parents=True, exist_ok=True)

    # Collect image paths
    if input_p.is_dir():
        images = sorted(p for p in input_p.iterdir() if p.suffix.lower() in _IMG_EXTS)
        if not images:
            print(f"No images found in {input_p}")
            sys.exit(1)
    elif input_p.is_file():
        images = [input_p]
    else:
        print(f"Path not found: {input_p}")
        sys.exit(1)

    print(f"\nFlood Severity Estimator  –  {len(images)} image(s)")
    print(f"Config: thresholds=({cfg.low_threshold}, {cfg.medium_threshold}, {cfg.high_threshold})")
    print("-" * 70)

    for img_path in images:
        process_image(estimator, img_path, save_p, display, args.panel_width)

    if display:
        cv2.destroyAllWindows()

    print("\nDone.")


if __name__ == "__main__":
    main()
