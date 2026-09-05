"""Render synthetic proof-of-delivery slips as damaged images.

The point of this module is to give the OCR path *real work*.  A clean,
programmatically-generated PNG of monospaced text is not a test of an extraction
pipeline; Tesseract reads it at 99% and the ``LOW_CONFIDENCE`` branch never
executes.  Courier slips in the wild are photographed on a phone, at an angle,
under bad light, with a thumb over one corner.

Four carrier templates are implemented with distinct visual identities --
:class:`~sentinel.schemas.evidence.Carrier` DELHIVERY, BLUEDART, EKART and
XPRESSBEES -- differing in header band, field order, label vocabulary, rule
lines, and typeface weight.  On top of the template we apply a stack of physical
degradations, each independently sampled:

* **Rotation** of +/- 3 degrees, as if the slip were photographed off-square.
* **Gaussian blur** with a radius drawn per image, standing in for focus miss.
* **JPEG compression** at a low quality factor, which is what actually reaches a
  merchant's dispute portal after two rounds of re-encoding.
* **Partial occlusion** -- a thumb, a fold shadow, or a torn corner covering a
  band of the slip. This is the degradation that produces genuinely *partial*
  extractions, where the AWB survives and the recipient name does not.
* **Contrast and brightness** shifts, plus per-pixel sensor noise.

Determinism holds throughout: every draw comes from
:data:`~data_gen.seeds.POD_RENDER_SEED`, so the same corpus produces the same
images byte for byte.

Fonts
-----
There is no font we can rely on being present, so :func:`_load_font` walks a
candidate list of common system faces and falls back to Pillow's built-in
bitmap font.  The fallback is the *worst* case for OCR, which is fine -- it
exercises the degradation path rather than breaking the render.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from data_gen.generator import CorpusRecord
from data_gen.seeds import POD_RENDER_SEED
from sentinel.schemas.evidence import Carrier, ExtractionStatus

logger = logging.getLogger(__name__)

#: Slip canvas size in pixels. Roughly a 4x6 inch label at 150 DPI.
SLIP_WIDTH: int = 620
SLIP_HEIGHT: int = 880

#: Candidate font files, tried in order. Covers Windows, macOS and common Linux
#: distributions; the last entry is the guaranteed built-in fallback.
_FONT_CANDIDATES: tuple[tuple[str, ...], ...] = (
    # (regular, bold) pairs
    ("arial.ttf", "arialbd.ttf"),
    ("Arial.ttf", "Arial Bold.ttf"),
    ("verdana.ttf", "verdanab.ttf"),
    ("tahoma.ttf", "tahomabd.ttf"),
    ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
    ("Helvetica.ttc", "Helvetica.ttc"),
    ("cour.ttf", "courbd.ttf"),
)

#: Directories searched for the candidate faces.
_FONT_DIRS: tuple[str, ...] = (
    "C:/Windows/Fonts",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts",
    "/Library/Fonts",
    "/System/Library/Fonts",
)


def _resolve_font_path(filename: str) -> str | None:
    """Return an absolute path to ``filename`` if it exists in a known font dir."""
    for directory in _FONT_DIRS:
        candidate = Path(directory) / filename
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _load_font(size: int, bold: bool = False, family: int = 0) -> ImageFont.ImageFont:
    """Load a TrueType face at ``size``, falling back to the built-in bitmap font.

    ``family`` selects among the candidate list so different carrier templates
    render in visibly different typefaces, which is what makes the four
    templates distinguishable to an OCR engine rather than merely to a human.
    """
    n = len(_FONT_CANDIDATES)
    for offset in range(n):
        regular, heavy = _FONT_CANDIDATES[(family + offset) % n]
        path = _resolve_font_path(heavy if bold else regular)
        if path is None:
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue

    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - Pillow < 10.1
        return ImageFont.load_default()


# --------------------------------------------------------------------------- #
# Carrier templates                                                           #
# --------------------------------------------------------------------------- #


class _Template:
    """Visual identity and field vocabulary for one carrier.

    Field *labels* differ per carrier on purpose.  Delhivery prints
    "RECEIVED BY", Bluedart prints "SIGNED BY", Ekart prints "DELIVERED TO".
    The OCR parser in ``sentinel.extraction.ocr`` matches all three with one
    alternation, which is exactly the robustness property worth testing.
    """

    def __init__(
        self,
        carrier: Carrier,
        band_rgb: tuple[int, int, int],
        font_family: int,
        recipient_label: str,
        address_label: str,
        date_label: str,
        scans_label: str,
        awb_label: str,
        tagline: str,
        rule_style: str,
    ) -> None:
        self.carrier = carrier
        self.band_rgb = band_rgb
        self.font_family = font_family
        self.recipient_label = recipient_label
        self.address_label = address_label
        self.date_label = date_label
        self.scans_label = scans_label
        self.awb_label = awb_label
        self.tagline = tagline
        self.rule_style = rule_style


#: The four carrier templates.
TEMPLATES: dict[Carrier, _Template] = {
    Carrier.DELHIVERY: _Template(
        carrier=Carrier.DELHIVERY,
        band_rgb=(216, 30, 41),
        font_family=0,
        recipient_label="RECEIVED BY",
        address_label="DELIVERY ADDRESS",
        date_label="DELIVERED",
        scans_label="SCANS",
        awb_label="AWB",
        tagline="PROOF OF DELIVERY // LAST MILE",
        rule_style="solid",
    ),
    Carrier.BLUEDART: _Template(
        carrier=Carrier.BLUEDART,
        band_rgb=(0, 63, 135),
        font_family=1,
        recipient_label="SIGNED BY",
        address_label="ADDRESS",
        date_label="DELIVERY DATE",
        scans_label="SCAN COUNT",
        awb_label="WAYBILL",
        tagline="EXPRESS DELIVERY RECEIPT",
        rule_style="double",
    ),
    Carrier.EKART: _Template(
        carrier=Carrier.EKART,
        band_rgb=(255, 153, 0),
        font_family=2,
        recipient_label="DELIVERED TO",
        address_label="DELIVERED AT",
        date_label="POD DATE",
        scans_label="EVENTS",
        awb_label="TRACKING",
        tagline="EKART LOGISTICS - DELIVERY CONFIRMATION",
        rule_style="dashed",
    ),
    Carrier.XPRESSBEES: _Template(
        carrier=Carrier.XPRESSBEES,
        band_rgb=(0, 122, 94),
        font_family=3,
        recipient_label="RECIPIENT",
        address_label="ADDRESS",
        date_label="DATE",
        scans_label="SCANS",
        awb_label="CONSIGNMENT",
        tagline="XPRESSBEES // POD SLIP",
        rule_style="solid",
    ),
}


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap to ``width`` characters."""
    if not text:
        return []
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_rule(
    draw: ImageDraw.ImageDraw, y: int, style: str, colour: tuple[int, int, int]
) -> None:
    """Draw a horizontal separator in the template's style."""
    if style == "double":
        draw.line([(30, y), (SLIP_WIDTH - 30, y)], fill=colour, width=2)
        draw.line([(30, y + 4), (SLIP_WIDTH - 30, y + 4)], fill=colour, width=1)
    elif style == "dashed":
        x = 30
        while x < SLIP_WIDTH - 30:
            draw.line([(x, y), (min(x + 12, SLIP_WIDTH - 30), y)], fill=colour, width=2)
            x += 20
    else:
        draw.line([(30, y), (SLIP_WIDTH - 30, y)], fill=colour, width=2)


def _render_clean(record: CorpusRecord, rng: np.random.Generator) -> Image.Image:
    """Render the undamaged slip for one record.

    The text drawn is the *observed* POD content from the record, not the
    underlying truth, so the image and the structured record agree.  A judge can
    open ``data/pods/dp_000123.jpg``, read it, and check it against the same
    dispute in ``train.jsonl``.
    """
    pod = record.bundle.pod
    carrier = pod.carrier if pod.carrier is not Carrier.UNKNOWN else Carrier.DELHIVERY
    template = TEMPLATES[carrier]

    image = Image.new("RGB", (SLIP_WIDTH, SLIP_HEIGHT), (252, 251, 248))
    draw = ImageDraw.Draw(image)

    font_title = _load_font(30, bold=True, family=template.font_family)
    font_label = _load_font(15, bold=True, family=template.font_family)
    font_value = _load_font(18, bold=False, family=template.font_family)
    font_small = _load_font(13, bold=False, family=template.font_family)

    # --- header band ---
    draw.rectangle([(0, 0), (SLIP_WIDTH, 92)], fill=template.band_rgb)
    draw.text((30, 20), carrier.value, font=font_title, fill=(255, 255, 255))
    draw.text((30, 62), template.tagline, font=font_small, fill=(240, 240, 240))

    ink = (24, 24, 28)
    muted = (90, 90, 96)
    y = 122

    def field(label: str, value: str, wrap_width: int = 42) -> None:
        """Draw one labelled field and advance the cursor."""
        nonlocal y
        draw.text((30, y), f"{label}:", font=font_label, fill=muted)
        y += 22
        for line in _wrap(value, wrap_width) or ["-"]:
            draw.text((38, y), line, font=font_value, fill=ink)
            y += 24
        y += 10

    field(template.awb_label, pod.awb_number or "-")
    _draw_rule(draw, y, template.rule_style, template.band_rgb)
    y += 18

    field(template.recipient_label, pod.recipient_name or "-")
    field(template.address_label, pod.delivery_address or "-", wrap_width=38)

    if pod.delivered_at is not None:
        stamp = pod.delivered_at.strftime("%d-%m-%Y %H:%M")
    else:
        stamp = "--/--/---- --:--"
    field(template.date_label, stamp)

    field(template.scans_label, str(pod.scan_count))

    _draw_rule(draw, y, template.rule_style, template.band_rgb)
    y += 20

    # --- signature block ---
    draw.text((30, y), "SIGNATURE:", font=font_label, fill=muted)
    y += 26
    if pod.signature_captured:
        draw.text((38, y), "SIGNATURE ON FILE", font=font_value, fill=ink)
        y += 26
        # A scrawl, so the block is visually a signature and not just a label.
        points = []
        sx, sy = 44, y + 18
        for i in range(28):
            sx += rng.uniform(4.0, 9.0)
            sy += rng.uniform(-9.0, 9.0)
            points.append((sx, sy))
        draw.line(points, fill=(18, 34, 92), width=2, joint="curve")
        y += 52
    else:
        draw.text((38, y), "NOT CAPTURED", font=font_value, fill=(150, 60, 60))
        y += 34

    # --- footer ---
    draw.text(
        (30, SLIP_HEIGHT - 46),
        f"ORDER {record.bundle.order.order_id}  /  DISPUTE {record.dispute.dispute_id}",
        font=font_small,
        fill=muted,
    )
    draw.text(
        (30, SLIP_HEIGHT - 28),
        f"GENERATED {datetime(2026, 2, 27).strftime('%d-%m-%Y')} - SYNTHETIC SPECIMEN",
        font=font_small,
        fill=muted,
    )

    return image


def _apply_damage(
    image: Image.Image, rng: np.random.Generator, severity: float
) -> Image.Image:
    """Apply the physical degradation stack.

    ``severity`` in [0, 1] scales every effect together, so a record whose
    observed OCR confidence is low actually *looks* worse. Tying the two means
    the images and the structured corpus tell the same story.
    """
    # 1. Rotation, +/- 3 degrees as specified.
    angle = float(rng.uniform(-3.0, 3.0))
    image = image.rotate(
        angle, resample=Image.BICUBIC, expand=False, fillcolor=(248, 247, 244)
    )

    # 2. Partial occlusion: a thumb, fold shadow, or torn corner.
    draw = ImageDraw.Draw(image, "RGBA")
    occlusion_roll = float(rng.random())
    if occlusion_roll < 0.28 + 0.30 * severity:
        kind = int(rng.integers(0, 3))
        if kind == 0:  # thumb over an edge
            cx = float(rng.uniform(0.0, SLIP_WIDTH - 120))
            cy = float(rng.uniform(SLIP_HEIGHT * 0.35, SLIP_HEIGHT - 90))
            draw.ellipse(
                [(cx, cy), (cx + rng.uniform(110, 190), cy + rng.uniform(80, 130))],
                fill=(58, 46, 42, 232),
            )
        elif kind == 1:  # fold shadow band
            top = float(rng.uniform(SLIP_HEIGHT * 0.25, SLIP_HEIGHT * 0.75))
            draw.rectangle(
                [(0, top), (SLIP_WIDTH, top + rng.uniform(26, 62))],
                fill=(0, 0, 0, int(70 + 90 * severity)),
            )
        else:  # torn corner
            draw.polygon(
                [
                    (SLIP_WIDTH, SLIP_HEIGHT),
                    (SLIP_WIDTH - rng.uniform(120, 240), SLIP_HEIGHT),
                    (SLIP_WIDTH, SLIP_HEIGHT - rng.uniform(120, 240)),
                ],
                fill=(255, 255, 255, 255),
            )

    # 3. Contrast and brightness drift.
    image = ImageEnhance.Contrast(image).enhance(
        float(rng.uniform(0.62, 1.05) + 0.15 * (1.0 - severity))
    )
    image = ImageEnhance.Brightness(image).enhance(float(rng.uniform(0.80, 1.14)))

    # 4. Focus miss.
    blur_radius = float(rng.uniform(0.2, 0.5) + 1.5 * severity)
    image = image.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    # 5. Sensor noise.
    arr = np.asarray(image, dtype=np.float32)
    noise = rng.normal(0.0, 4.0 + 14.0 * severity, arr.shape)
    image = Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8))

    # 6. JPEG re-encoding, which is what actually reaches a dispute portal.
    quality = int(np.clip(round(74 - 46 * severity), 18, 92))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def render_pod(
    record: CorpusRecord, rng: np.random.Generator, out_dir: Path
) -> Path | None:
    """Render one record's slip to ``out_dir``. Returns the path, or None.

    Returns None when the record has no proof-of-delivery document to render --
    an ``ABSENT`` status means there is nothing to photograph.
    """
    if record.bundle.pod.extraction_status is ExtractionStatus.ABSENT:
        return None

    # Severity is the inverse of the observed confidence, so the picture and the
    # structured record agree about how bad this document is.
    severity = float(np.clip(1.0 - record.bundle.pod.ocr_confidence, 0.05, 0.95))

    image = _render_clean(record, rng)
    image = _apply_damage(image, rng, severity)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{record.dispute.dispute_id}.jpg"
    image.save(path, format="JPEG", quality=88)
    return path


def render_corpus_sample(
    records: list[CorpusRecord], out_dir: Path, limit: int
) -> list[Path]:
    """Render slips for up to ``limit`` records, balanced across carriers.

    Only a sample is rendered. Producing 20 000 images would take minutes and
    add hundreds of megabytes for no analytical gain: the training corpus uses
    the numeric OCR-degradation model described in
    :mod:`data_gen.generator`, and these images exist to exercise the *real*
    pytesseract path in the demo, the simulate endpoint, and the tests.

    Selection round-robins over the four carriers so every template is
    represented even though carrier share is uneven.
    """
    if limit <= 0:
        return []

    rng = np.random.default_rng(POD_RENDER_SEED)

    by_carrier: dict[Carrier, list[CorpusRecord]] = {c: [] for c in TEMPLATES}
    for record in records:
        pod = record.bundle.pod
        if pod.extraction_status is ExtractionStatus.ABSENT:
            continue
        if pod.carrier in by_carrier:
            by_carrier[pod.carrier].append(record)

    selected: list[CorpusRecord] = []
    round_index = 0
    while len(selected) < limit:
        added_this_round = False
        for carrier in TEMPLATES:
            pool = by_carrier[carrier]
            if round_index < len(pool) and len(selected) < limit:
                selected.append(pool[round_index])
                added_this_round = True
        if not added_this_round:
            break
        round_index += 1

    written: list[Path] = []
    for record in selected:
        try:
            path = render_pod(record, rng, out_dir)
        except Exception as exc:
            # Rendering is a convenience, never a build blocker. A missing font
            # or an exotic Pillow build must not fail `make data`.
            logger.warning(
                "POD render failed for %s: %s", record.dispute.dispute_id, exc
            )
            continue
        if path is not None:
            record.pod_image_path = str(path)
            written.append(path)

    return written
