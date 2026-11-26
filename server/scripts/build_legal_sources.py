"""Build data/legal/sources.yaml from the already-downloaded files in data/legal/raw/.

Run with: .venv\\Scripts\\python.exe -I scripts\\build_legal_sources.py
It never fetches anything and never runs code from raw/. It extracts text next to each
download (extracted.txt), hashes the raw file and the text, and writes sources.yaml.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
from pathlib import Path

import yaml
from pypdf import PdfReader

logging.getLogger("pypdf").setLevel(logging.ERROR)

LEGAL = Path(__file__).resolve().parent.parent / "data" / "legal"
RAW = LEGAL / "raw"
FETCHED_AT = "2026-11-26"

AVAILABLE = [
    {
        "id": "cpa2019_egazette",
        "title": "The Consumer Protection Act, 2019 (No. 35 of 2019), Gazette of India Extraordinary, as enacted",
        "url": "https://egazette.gov.in/WriteReadData/2019/210422.pdf",
        "issuer": "Ministry of Law and Justice (Legislative Department), egazette.gov.in",
        "file": "cpa2019_egazette/210422.pdf",
        "content_type": "application/pdf",
        "notes": "Text as published on 9 Aug 2019, not a consolidated version.",
    },
    {
        "id": "ecom_rules_2020_egazette",
        "title": "Consumer Protection (E-Commerce) Rules, 2020, G.S.R. 462(E) of 23 July 2020",
        "url": "https://egazette.gov.in/WriteReadData/2020/220661.pdf",
        "issuer": "Department of Consumer Affairs, egazette.gov.in",
        "file": "ecom2020_egazette/220661.pdf",
        "content_type": "application/pdf",
        "notes": "Bilingual gazette PDF; the Hindi text extracts imperfectly, the English text is clean. Original 2020 text, any later amendment is not included.",
    },
    {
        "id": "rbi_ios_2021_notification",
        "title": "RBI notification: Reserve Bank - Integrated Ombudsman Scheme, 2021 (CEPD.PRD.No.S873, 12 Nov 2021)",
        "url": "https://www.rbi.org.in/Scripts/FS_Notification.aspx?Id=12192&fn=2745&Mode=0",
        "issuer": "Reserve Bank of India",
        "file": "rbi_ios_2021_notification/FS_Notification_12192.html",
        "content_type": "text/html",
        "notes": "HTML page with the notification text. The full Scheme PDF is unavailable (see rbi_ios_2021_scheme_pdf).",
    },
    {
        "id": "rbi_ios_2022_amendment_notification",
        "title": "RBI notification: Integrated Ombudsman Scheme amendment for Credit Information Companies (5 Aug 2022)",
        "url": "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12371&Mode=0",
        "issuer": "Reserve Bank of India",
        "file": "rbi_ios_2022_amendment_notification/NotificationUser_12371.html",
        "content_type": "text/html",
        "notes": "Amendment notification page; the annexed updated Scheme PDF is not reachable.",
    },
    {
        "id": "rbi_pr1184",
        "title": "RBI press release PR1184: The Reserve Bank - Integrated Ombudsman Scheme, 2021 (12 Nov 2021)",
        "url": "https://www.rbi.org.in/commonman/Upload/English/PressRelease/PDFs/PR1184ENG121121.pdf",
        "issuer": "Reserve Bank of India",
        "file": "rbi_pr1184/PR1184ENG121121.pdf",
        "content_type": "application/pdf",
        "notes": "States the CMS portal, the Chandigarh processing centre and the 14448 contact centre.",
    },
    {
        "id": "nch_home",
        "title": "National Consumer Helpline (NCH 2.0) home page",
        "url": "https://consumerhelpline.gov.in/public/",
        "issuer": "Department of Consumer Affairs",
        "file": "helpline_home/index.html",
        "content_type": "text/html",
        "notes": "Escalation target page: helpline numbers, WhatsApp, web portal, app.",
    },
    {
        "id": "nch_about",
        "title": "National Consumer Helpline: About us",
        "url": "https://consumerhelpline.gov.in/public/about",
        "issuer": "Department of Consumer Affairs",
        "file": "helpline_about/about.html",
        "content_type": "text/html",
        "notes": "Describes NCH as a pre-litigation step before the consumer commission.",
    },
    {
        "id": "pib_ejagriti_2269994",
        "title": "PIB release: e-Jagriti wins Silver Award at National Awards for e-Governance 2026",
        "url": "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2269994",
        "issuer": "Press Information Bureau, Ministry of Consumer Affairs, Food and Public Distribution",
        "file": "pib_2269994/PressReleasePage.html",
        "content_type": "text/html",
        "notes": "Official statement that e-Jagriti (launched 1 Jan 2025) unified e-Daakhil, OCMS, NCDRC CMS and CONFONET.",
    },
    {
        "id": "ejagriti_home",
        "title": "e-Jagriti platform (Department of Consumer Affairs) landing page",
        "url": "https://e-jagriti.gov.in/",
        "issuer": "Department of Consumer Affairs",
        "file": "ejagriti_home/index.html",
        "content_type": "text/html",
        "notes": "Client-rendered shell with no readable text; kept only to show the URL resolves. Use pib_ejagriti_2269994 for facts.",
    },
]

UNAVAILABLE = [
    {
        "id": "cpa2019_indiacode_pdf",
        "title": "Consumer Protection Act, 2019, India Code PDF (handle 123456789/15256)",
        "url": "https://www.indiacode.nic.in/bitstream/123456789/15256/1/a2019-35.pdf",
        "reason": "HTTP 302 to an HTML page of about 18 KB on every attempt (plain, -L, browser user agent); no PDF bytes served.",
    },
    {
        "id": "consumeraffairs_nic_cp_act_pdf",
        "title": "Consumer Protection Act 2019 PDF on consumeraffairs.nic.in",
        "url": "https://consumeraffairs.nic.in/sites/default/files/CP%20Act%202019.pdf",
        "reason": "Connection failed (no HTTP status) on repeated attempts.",
    },
    {
        "id": "egazette_nic_in_host",
        "title": "egazette.nic.in gazette PDFs",
        "url": "https://egazette.nic.in/WriteReadData/2019/210422.pdf",
        "reason": "Host name does not resolve; the same files were fetched from egazette.gov.in instead.",
    },
    {
        "id": "edaakhil_nic_in",
        "title": "e-Daakhil portal (edaakhil.nic.in)",
        "url": "https://edaakhil.nic.in/",
        "reason": "Connection failed on edaakhil.nic.in, e-daakhil.nic.in and the /edaakhil/ path. Official sources say e-Jagriti has replaced e-Daakhil (see pib_ejagriti_2269994).",
    },
    {
        "id": "rbi_ios_2021_scheme_pdf",
        "title": "Reserve Bank - Integrated Ombudsman Scheme, 2021, full Scheme PDF",
        "url": "https://rbidocs.rbi.org.in/rdocs/content/pdfs/RBIOS2021_121121_A.pdf",
        "reason": "rbidocs.rbi.org.in returns a human-verification (CAPTCHA) page instead of the PDF for curl and WebFetch, on this and other rbidocs and cms.rbi.org.in paths. Not bypassed. Notification text and press release are used instead.",
    },
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts = [f"--- page {i} ---\n{page.extract_text() or ''}" for i, page in enumerate(reader.pages, 1)]
    return "\n\n".join(parts) + "\n"


def html_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", "", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d|table|ul|ol)>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", "", raw)
    text = html.unescape(raw)
    text = "\n".join(line.strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def main() -> None:
    sources = []
    for item in AVAILABLE:
        path = RAW / item["file"]
        text = pdf_text(path) if item["content_type"] == "application/pdf" else html_text(path)
        text_path = path.parent / "extracted.txt"
        text_path.write_text(text, encoding="utf-8", newline="\n")
        sources.append(
            {
                "id": item["id"],
                "title": item["title"],
                "url": item["url"],
                "issuer": item["issuer"],
                "fetched_at": FETCHED_AT,
                "status": "available",
                "content_type": item["content_type"],
                "file": f"raw/{item['file']}",
                "size_bytes": path.stat().st_size,
                "sha256": sha256_of(path),
                "text_file": f"raw/{item['file'].rsplit('/', 1)[0]}/extracted.txt",
                "text_sha256": sha256_of(text_path),
                "notes": item["notes"],
            }
        )
    for item in UNAVAILABLE:
        sources.append(
            {
                "id": item["id"],
                "title": item["title"],
                "url": item["url"],
                "fetched_at": FETCHED_AT,
                "status": "unavailable",
                "sha256": None,
                "reason": item["reason"],
            }
        )
    out = LEGAL / "sources.yaml"
    out.write_text(
        "# Generated by scripts/build_legal_sources.py. fetched_at is the date of the fetch attempt.\n"
        + yaml.safe_dump({"sources": sources}, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {out} ({len(sources)} sources)")


if __name__ == "__main__":
    main()
