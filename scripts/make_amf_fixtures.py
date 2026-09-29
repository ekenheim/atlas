"""Write the AMF info-financière fixtures in `tests/fixtures/amf/soitec/`, deterministically.

    uv run python scripts/make_amf_fixtures.py [OUT_DIR]

**Hand-written, not recorded.** The shapes follow the documented Opendatasoft Explore API
v2.0 (<https://www.data.gouv.fr/dataservices/api-info-financiere>) as the API served it on
2026-09-29 to a handful of requests made to learn them (docs/decisions.md, "AMF
info-financière for Soitec"): the records answer (`total_count`, `links`, `records[]` with
`record.{id, timestamp, size, fields}` and the `flux-amf-new-prod` field names below),
file links under `https://fr.ftp.opendatasoft.com/datadila/INFOFI/` served as
`application/pdf` with `Last-Modified` and `ETag`, and the two hosts' robots.txt exactly as
read that day. Every identifier, time and document here is invented; the documents are
synthetic and say so, and their figures are not Soitec's.

- `records.json`: four rows, newest first by transmission time: an AMF threshold-crossing
  decision (French), Soitec's annual financial report as an ESEF package (a .zip: skipped),
  and Soitec's full-year results in English and in French (PDF; the AMF time three seconds
  after the transmission time)
- the three PDFs under the paths the rows link to
- `robots-info-financiere.txt`, `robots-opendatasoft.txt`: the robots.txt bodies
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_pdf_fixtures import document, text_stream

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "amf" / "soitec"
SITE = "https://www.info-financiere.gouv.fr"
RECORDS = f"{SITE}/api/explore/v2.0/catalog/datasets/flux-amf-new-prod/records"
FILES = "https://fr.ftp.opendatasoft.com/datadila/INFOFI/"
SYNTHETIC = "SYNTHETIC TEST FIXTURE: not an AMF document; every figure is invented."
SOITEC_LEI = "969500ZR92SQCU9TST26"

THRESHOLD = "307/8888/01/FC307900001_20260824.pdf"
ESEF = "MKW/2026/06/FCMKW119500_20260617.zip"
RESULTS_EN = "MKW/2026/06/FCMKW119000_20260610.pdf"
RESULTS_FR = "MKW/2026/06/FCMKW139000_20260610.pdf"

RESULTS_EN_PAGES = [
    [SYNTHETIC, "Soitec reports full-year 2026 results", "Bernin (Grenoble), France"],
    [
        "Full-year results",
        "Revenue from Photonics-SOI substrates grew strongly in the year, driven by",
        "demand for silicon photonics transceivers in AI data centres. Soitec expects",
        "Photonics-SOI to remain the fastest-growing part of its revenue next year.",
    ],
]
RESULTS_FR_PAGES = [
    [SYNTHETIC, "Soitec publie ses résultats annuels 2026", "Bernin (Grenoble), France"],
    [
        "Résultats annuels",
        "Le chiffre d'affaires des plaques Photonics-SOI a fortement progressé sur",
        "l'exercice, porté par la demande de transceivers optiques pour les centres",
        "de données. Soitec prévoit que cette activité restera la plus dynamique.",
    ],
]
THRESHOLD_PAGES = [
    [
        SYNTHETIC,
        "Déclaration de franchissement de seuil",
        "Une société de gestion a déclaré avoir franchi à la hausse le seuil de 5 %",
        "du capital et des droits de vote de la société SOITEC.",
    ],
]


def fields(
    uin: str,
    link: str,
    diffuser: str,
    title: str,
    language: str,
    transmitted: str,
    sent_to_amf: str,
    kind: str,
    subtype_fr: str,
    subtype_en: str,
    lists: list[str],
) -> dict[str, object]:
    return {
        "uin_ver_fin": "FI_v1.1_20120515",
        "uin_ver_lov": "LV_01.09_20180501",
        "uin_idt_uin": uin,
        "uin_dat_amf": sent_to_amf,
        "uin_dat_mar": "8887-12-31T22:00:00+00:00",
        "filename": "Nouveau",
        "identificationdiffuseur_idi_cod_dif": diffuser,
        "identificationsociete_iso_nom_soc": "SOITEC",
        "identificationsociete_iso_cd_amf": None,
        "identificationsociete_iso_url_irg": None,
        "identificationsociete_iso_pay_ss": "FR",
        "identificationsociete_iso_cd_isi": "FR0013227113",
        "identificationsociete_iso_url_int": None,
        "identificationsociete_iso_url_log": None,
        "identificationsociete_iso_cd_lei": SOITEC_LEI,
        "fichierdecontenu_inf_fic_nom": link,
        "informationdeposee_inf_dat_emt": transmitted,
        "informationdeposee_inf_tit_inf": title,
        "informationdeposee_inf_stp_pri": "023000" if diffuser == "307" else "010100",
        "informationdeposee_inf_cod_dif": "OPT" if diffuser == "307" else "OBL",
        "informationdeposee_inf_stp_inf": "023000" if diffuser == "307" else "010100",
        "informationdeposee_inf_lst_dif": lists,
        "informationdeposee_inf_lng_inf": language,
        "identificationsociete_iso_code_tkr_iso_cd_mch": "99",
        "identificationsociete_iso_code_tkr_iso_cd_tkr": "SOI",
        "informationdeposee_inf_upg_inf_inf_upg_rel": None,
        "informationdeposee_inf_upg_inf_inf_upg_sts": "NEW",
        "url_de_recuperation": FILES + link,
        "timezone_uin_dat_amf": "02:00",
        "cac40": None,
        "name_cac40": None,
        "type_d_information": kind,
        "sous_type_d_information": subtype_fr,
        "type_of_information": (
            "Ongoing regulated information"
            if kind == "Informations réglementées continues"
            else "Periodic regulated information"
        ),
        "subtype_of_information": subtype_en,
        "type_informationn": f"{kind}>{subtype_fr}",
        "type_d_information_ancien": None,
        "type_d_information_nouveau": kind,
        "type_of_information_ancien": None,
        "type_of_information_nouveau": None,
        "code_isin_nom_sc": "SOITEC (FR0013227113)",
    }


def records() -> bytes:
    wire = ["AMF", "Euronext", "Bloomberg", "Dow Jones"]
    continuous = "Informations réglementées continues"
    periodic = "Informations réglementées périodiques"
    rows = [
        ("0f3a5c9e1b7d2468ace013579bdf2468ace01357", "2026-08-24T14:10:00Z", fields(
            "900001_20260824", THRESHOLD, "307", "Franchissement de seuil", "Français",
            "2026-08-24T14:06:22+00:00", "2026-08-24T14:06:22+00:00", continuous,
            "Décision de franchissement de seuil", "NULL", ["AMF"],
        )),
        ("1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d", "2026-06-17T16:00:00Z", fields(
            "119500_20260617", ESEF, "MKW", "Rapport financier annuel 2025-2026 (ESEF)",
            "Français", "2026-06-17T15:45:00+00:00", "2026-06-17T15:45:00+00:00", periodic,
            "Rapport financier annuel", "Annual financial report", wire,
        )),
        ("2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e", "2026-06-10T06:00:00Z", fields(
            "119000_20260610", RESULTS_EN, "MKW", "Soitec reports full-year 2026 results",
            "Anglais", "2026-06-10T05:45:00+00:00", "2026-06-10T05:45:03+00:00", continuous,
            "Communiqué sur l'information financière annuelle", "Annual financial information",
            wire,
        )),
        ("3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f", "2026-06-10T06:00:00Z", fields(
            "139000_20260610", RESULTS_FR, "MKW", "Soitec publie ses résultats annuels 2026",
            "Français", "2026-06-10T05:45:00+00:00", "2026-06-10T05:45:03+00:00", continuous,
            "Communiqué sur l'information financière annuelle", "Annual financial information",
            wire,
        )),
    ]  # fmt: skip
    dataset = f"{SITE}/api/explore/v2.0/catalog/datasets/flux-amf-new-prod"
    answer = {
        "total_count": len(rows),
        "links": [
            {"rel": "self", "href": f"{RECORDS}?limit=100&offset=0"},
            {"rel": "first", "href": f"{RECORDS}?limit=100&offset=0"},
            {"rel": "last", "href": f"{RECORDS}?limit=100&offset=0"},
        ],
        "records": [
            {
                "links": [
                    {"rel": "self", "href": f"{RECORDS}/{record_id}"},
                    {"rel": "datasets", "href": f"{SITE}/api/explore/v2.0/catalog/datasets"},
                    {"rel": "dataset", "href": dataset},
                ],
                "record": {"id": record_id, "timestamp": updated, "size": 780, "fields": row},
            }
            for record_id, updated, row in rows
        ],
    }
    return (json.dumps(answer, indent=1, ensure_ascii=False) + "\n").encode()


# As served on 2026-09-29.
ROBOTS_INFO_FINANCIERE = b"""User-agent: Twitterbot
Disallow:

User-agent: *
Disallow: /logout
Disallow: /login
Disallow: /publish
Disallow: /backoffice
Disallow: /explore/download
Disallow: /explore/dataset/*/download
Disallow: /explore/dataset/*/rss/
Disallow: /explore/dataset/*/atom/
Disallow: /api/
Disallow: /p-preview/
Disallow: /explore/form-preview/
Disallow: /static/

User-agent: Googlebot
Allow: /api/
Allow: /static/
Disallow: /api/v2/*/exports/
Disallow: /api/explore/v2*/exports/
Disallow: /explore/assets/
Disallow: /glossary/

Sitemap: https://info-financiere.gouv.fr/sitemap.xml
"""
ROBOTS_OPENDATASOFT = b"User-agent: *\nDisallow: /\n"


def fixtures() -> dict[str, bytes]:
    files = {
        "records.json": records(),
        "robots-info-financiere.txt": ROBOTS_INFO_FINANCIERE,
        "robots-opendatasoft.txt": ROBOTS_OPENDATASOFT,
        RESULTS_EN: document([text_stream(p) for p in RESULTS_EN_PAGES]),
        RESULTS_FR: document([text_stream(p) for p in RESULTS_FR_PAGES]),
        THRESHOLD: document([text_stream(p) for p in THRESHOLD_PAGES]),
    }
    text = {"Content-Type": "text/plain; charset=utf-8"}
    pdf = {"Content-Type": "application/pdf"}
    manifest = {
        "note": (
            "Hand-written in the shapes the AMF info-financière API (Opendatasoft Explore v2.0)"
            " served on 2026-09-29, not recorded (scripts/make_amf_fixtures.py). Identifiers,"
            " times and documents are synthetic; the robots.txt bodies are as served."
        ),
        "responses": [
            {"url": f"{SITE}/robots.txt", "file": "robots-info-financiere.txt",
             "headers": text},
            {"url": "https://fr.ftp.opendatasoft.com/robots.txt",
             "file": "robots-opendatasoft.txt", "headers": {"Content-Type": "text/plain"}},
            {"url": RECORDS, "file": "records.json", "ignore_query": True,
             "headers": {"Content-Type": "application/json; charset=utf-8"}},
            {"url": FILES + RESULTS_EN, "file": RESULTS_EN,
             "headers": pdf | {"Last-Modified": "Wed, 10 Jun 2026 05:50:12 GMT",
                               "ETag": '"6a98657e-1001"'}},
            {"url": FILES + RESULTS_FR, "file": RESULTS_FR,
             "headers": pdf | {"Last-Modified": "Wed, 10 Jun 2026 05:50:14 GMT",
                               "ETag": '"6a98657e-1002"'}},
            {"url": FILES + THRESHOLD, "file": THRESHOLD,
             "headers": pdf | {"Last-Modified": "Mon, 24 Aug 2026 14:08:01 GMT",
                               "ETag": '"6a98657e-1003"'}},
        ],
    }  # fmt: skip
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    return files


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    for name, data in fixtures().items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"wrote {path} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
