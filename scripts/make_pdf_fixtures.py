"""Write the small PDF fixtures in `tests/fixtures/pdf/`, byte for byte deterministically.

    uv run python scripts/make_pdf_fixtures.py [OUT_DIR]

The PDFs are written by hand here (no PDF library, no clock, no random `/ID`), so the
same script always makes the same bytes; `tests/unit/test_pdf_parsing.py` checks that the
checked-in files are exactly what it makes. They are synthetic stand-ins for the kinds of
PDF the exchange adapters fetch, not copies of any issuer's document:

- `annual-report-en.pdf`: three text pages in English, the document language declared in
  the catalog (`/Lang (en-GB)`), page labels `i`, `1`, `2` (a roman cover page), and
  WinAnsi characters outside ASCII (an en dash, a euro sign, curly quotes).
- `results-fr.pdf`: a two-page French results announcement with no declared language.
- `scanned.pdf`: two pages that are only an image each (as a scan without OCR is).
"""

import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pdf"

ANNUAL_REPORT_EN = [
    [
        "Photonics Example plc",
        "Annual Report and Accounts 2026",
    ],
    [
        "Chair's statement",
        "Revenue grew 18% to €412.6 million in the year ended 30 June 2026.",
        "Demand for 800G transceivers \u2013 driven by AI data centres \u2013 exceeded supply.",
        "We supply indium phosphide epitaxial wafers to “Tier 1” laser makers.",
    ],
    [
        "Principal risks",
        "Our largest customer accounted for 31% of revenue.",
        "Capacity at the Newport fab will double by the end of fiscal 2027.",
    ],
]

RESULTS_FR = [
    [
        "Résultats du premier semestre de l'exercice 2027",
        "Le chiffre d'affaires s'est établi à 381 millions d'euros, en hausse de 12 %.",
        "La demande pour les plaques de silicium sur isolant est restée forte dans",
        "les communications optiques et les centres de données.",
    ],
    [
        "Perspectives",
        "Nous confirmons nos objectifs pour l'exercice et nous prévoyons une marge",
        "stable par rapport à l'année précédente.",
    ],
]


def literal(text: str) -> bytes:
    """A PDF literal string in WinAnsiEncoding (cp1252), escaped."""
    data = text.encode("cp1252")
    for special in (b"\\", b"(", b")"):
        data = data.replace(special, b"\\" + special)
    return b"(" + data + b")"


def text_stream(lines: list[str]) -> bytes:
    body = [b"BT", b"/F1 11 Tf", b"14 TL", b"72 760 Td"]
    for index, line in enumerate(lines):
        if index:
            body.append(b"T*")
        body.append(literal(line) + b" Tj")
    body.append(b"ET")
    return b"\n".join(body) + b"\n"


def image_stream() -> bytes:
    return b"q\n468 648 0 0 72 72 cm\n/Im1 Do\nQ\n"


def stream(dictionary: bytes, data: bytes) -> bytes:
    # Uncompressed: a compressor's output can differ between zlib builds.
    head = b"<< " + dictionary + (b" " if dictionary else b"") + b"/Length "
    return head + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream"


def assemble(objects: list[bytes]) -> bytes:
    """A PDF file of `objects` (object 1 is the catalog), with an exact xref table."""
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    out += f"startxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def document(contents: list[bytes], *, catalog_extra: bytes = b"", image: bool = False) -> bytes:
    """Catalog (1), Pages (2), a font (3), an image (4, if any), then a page and its
    content stream per page."""
    first_page = 5 if image else 4
    page_numbers = [first_page + 2 * index for index in range(len(contents))]
    kids = b" ".join(f"{number} 0 R".encode() for number in page_numbers)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R" + catalog_extra + b" >>",
        b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(contents)).encode() + b" >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    if image:
        pixels = bytes((x * 32 + y * 8) % 256 for y in range(16) for x in range(16))
        objects.append(
            stream(
                b"/Type /XObject /Subtype /Image /Width 16 /Height 16"
                b" /ColorSpace /DeviceGray /BitsPerComponent 8",
                pixels,
            )
        )
    resources = b"/Font << /F1 3 0 R >>" + (b" /XObject << /Im1 4 0 R >>" if image else b"")
    for number, content in zip(page_numbers, contents, strict=True):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << "
            + resources
            + b" >> /Contents "
            + str(number + 1).encode()
            + b" 0 R >>"
        )
        objects.append(stream(b"", content))
    return assemble(objects)


def fixtures() -> dict[str, bytes]:
    return {
        "annual-report-en.pdf": document(
            [text_stream(page) for page in ANNUAL_REPORT_EN],
            catalog_extra=(b" /Lang (en-GB) /PageLabels << /Nums [0 << /S /r >> 1 << /S /D >>] >>"),
        ),
        "results-fr.pdf": document([text_stream(page) for page in RESULTS_FR]),
        "scanned.pdf": document([image_stream(), image_stream()], image=True),
    }


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    out.mkdir(parents=True, exist_ok=True)
    for name, data in fixtures().items():
        (out / name).write_bytes(data)
        print(f"wrote {out / name} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
