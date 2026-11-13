"""Generate the frozen benchmark sites: eight labelled static sites, one defect per page.

The corpus is data, not code: this generator writes it once, the output is committed, and a test
re-digests it. Editing a site by hand is how the labels start lying, so change the spec here and
regenerate instead.

Each site has thirteen pages and ten planted defects — one per catalogued rule — while the three
remaining pages are clean on purpose: a corpus of only broken pages measures recall and nothing
about precision. Defects rotate by site, so the clean pages sit at different positions per site.

Pages are matched to findings by rule and page path. That is exactly the granularity of the
deterministic layer: one rule yields one finding per page, no matter how many nodes it names.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SITES_DIR = ROOT / "sites"
DATASET = ROOT / "dataset.json"

RULES = [
    "SEO-TITLE",
    "SEO-META-DESC",
    "SEO-H1",
    "A11Y-LANG",
    "A11Y-IMG-ALT",
    "A11Y-LABEL",
    "A11Y-BUTTON-NAME",
    "A11Y-LINK-NAME",
    "A11Y-CONTRAST",
    "LAYOUT-OCCLUSION",
]

PAGES = [
    ("index.html", "Home", "Field notes from the coast"),
    ("about.html", "About", "A studio of two, working slowly"),
    ("contact.html", "Contact", "Say hello"),
    ("blog/index.html", "Journal", "Everything we published"),
    ("blog/post-1.html", "Post one", "Tide tables as a design constraint"),
    ("blog/post-2.html", "Post two", "Printing with a two-colour press"),
    ("blog/post-3.html", "Post three", "A season of weather delays"),
    ("products/index.html", "Prints", "Editions and notebooks"),
    ("products/item-1.html", "Item one", "Coastline, edition of forty"),
    ("products/item-2.html", "Item two", "Harbour, edition of twenty"),
    ("spa.html", "App shell", "The working shell"),
    ("pricing.html", "Pricing", "Rates for commissioned work"),
    ("legal.html", "Legal", "Terms and privacy"),
]

SITES = [
    ("northwind", "Northwind Press"),
    ("saltmarsh", "Saltmarsh Studio"),
    ("lumen", "Lumen Workshop"),
    ("kilnhouse", "Kiln House"),
    ("fernhollow", "Fern Hollow"),
    ("tidewater", "Tidewater Editions"),
    ("oatfield", "Oatfield Bindery"),
    ("bright-anvil", "Bright Anvil"),
]

STYLE = """
    body { margin: 0; font-family: system-ui, sans-serif; color: #1b1b1b; background: #ffffff; }
    header { display: flex; justify-content: space-between; align-items: center;
             padding: 16px 24px; border-bottom: 1px solid #dcdcdc; position: relative; }
    .brand { color: #1b1b1b; font-weight: 600; text-decoration: none; }
    nav a { margin-left: 12px; color: #0b57d0; }
    main { padding: 24px; max-width: 720px; }
    .lede { color: #333333; font-size: 1.125rem; }
    .muted { color: #555555; }
    .faint { color: #9aa0a6; }
    form { display: flex; gap: 8px; margin-top: 12px; }
    input, button { font-size: 1rem; padding: 8px 12px; }
    footer { padding: 24px; color: #555555; border-top: 1px solid #dcdcdc; }
    .promo { position: absolute; right: 8px; top: 8px; display: flex; gap: 6px; padding: 6px 8px;
             background: #ffffff; border: 1px solid #dcdcdc; }
    @media (min-width: 768px) { .promo { position: static; } }
"""

ICON = (
    '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">'
    '<circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" /></svg>'
)
CLOSE_ICON = (
    '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">'
    '<path d="M1 1 L13 13 M13 1 L1 13" stroke="currentColor" /></svg>'
)


@dataclass(frozen=True)
class Page:
    path: str
    title: str
    headline: str


def defects_for(site_index: int, page_index: int) -> str | None:
    """Ten defects per site, one per rule, rotated so clean pages differ between sites."""
    if page_index >= len(RULES):
        return None
    return RULES[(page_index + site_index) % len(RULES)]


def body_for(page: Page, defect: str | None, brand: str) -> str:
    parts = [f'<h1>{page.headline}</h1>', '<p class="lede">Prints, notebooks and field notes.</p>']
    if defect == "SEO-H1":
        # The rule fires when a page has no h1 at all, so this page demotes its headline.
        parts[0] = f'<h2>{page.headline}</h2>'

    if defect == "A11Y-IMG-ALT":
        parts.append('<p>Latest proof, photographed on the press:</p>')
        parts.append('<img src="proof.png" width="240" height="160">')
    else:
        parts.append('<p>Latest proof, photographed on the press:</p>')
        parts.append(
            '<img src="proof.png" alt="A proof sheet on the press" width="240" height="160">'
        )

    if defect == "A11Y-CONTRAST":
        parts.append('<p class="faint">Colour proofs are posted every second Friday.</p>')
    else:
        parts.append('<p class="muted">Colour proofs are posted every second Friday.</p>')

    if defect == "A11Y-BUTTON-NAME":
        parts.append(f'<button type="button">{ICON}</button>')
    elif page.path == "contact.html" or page.path == "pricing.html":
        parts.append('<button type="button">Request a quote</button>')

    if defect == "A11Y-LINK-NAME":
        parts.append(f'<p><a href="https://example.com/feed">{ICON}</a></p>')
    elif page.path == "blog/index.html":
        parts.append('<p><a href="post-1.html">Read the latest post</a></p>')

    if defect == "A11Y-LABEL":
        # No placeholder: axe accepts one as an accessible name, and the input would be fine.
        parts.append(
            '<form><input type="email" name="email">'
            '<button type="submit">Send</button></form>'
        )
    elif page.path == "contact.html":
        parts.append(
            '<form><label for="email">Email</label>'
            '<input id="email" type="email" name="email">'
            '<button type="submit">Send</button></form>'
        )
    return "\n      ".join(parts)


def render(site_index: int, brand: str, page: Page, defect: str | None) -> str:
    html_attr = "" if defect == "A11Y-LANG" else ' lang="en"'
    head = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
    ]
    if defect != "SEO-TITLE":
        head.append(f"<title>{brand} — {page.title}</title>")
    if defect != "SEO-META-DESC":
        head.append(f'<meta name="description" content="{brand}: {page.title}.">')
    head.append(f"<style>{STYLE}</style>")

    banner = ""
    if defect == "LAYOUT-OCCLUSION":
        banner = (
            '<div class="promo" role="complementary" aria-label="Promotion">'
            '<span>Autumn sale</span>'
            '<a class="promo-close" href="#dismiss" aria-label="Dismiss promotion">'
            f"{CLOSE_ICON}</a></div>"
        )

    nav = "".join(
        f'<a href="{target}">{label}</a>'
        for target, label in (
            ("blog/index.html", "Journal"),
            ("products/index.html", "Prints"),
            ("about.html", "About"),
        )
    )
    return f"""<!doctype html>
<html{html_attr}>
  <head>
    {"".join(head)}
  </head>
  <body>
    <header>
      <a class="brand" href="index.html">{brand}</a>
      <nav aria-label="Sections">{nav}</nav>
      {banner}
    </header>
    <main>
      {body_for(page, defect, brand)}
    </main>
    <footer><p>© {brand}</p></footer>
  </body>
</html>
"""


def build() -> dict[str, Any]:
    """Write every page, then return the manifest that describes them."""
    for site_index, (slug, brand) in enumerate(SITES):
        for page_index, (path, title, headline) in enumerate(PAGES):
            page = Page(path=path, title=title, headline=headline)
            target = SITES_DIR / slug / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                render(site_index, brand, page, defects_for(site_index, page_index)),
                encoding="utf-8",
            )
    return manifest()


def manifest() -> dict[str, Any]:
    """The manifest a fresh generator would write, computed without touching the filesystem."""
    sites: list[dict[str, Any]] = []
    total_pages = 0
    for site_index, (slug, brand) in enumerate(SITES):
        labels: list[dict[str, str]] = []
        for page_index, (path, _title, _headline) in enumerate(PAGES):
            defect = defects_for(site_index, page_index)
            if defect is not None:
                labels.append({"page": path, "rule_id": defect})
        total_pages += len(PAGES)
        sites.append(
            {
                "slug": slug,
                "brand": brand,
                "base_url": f"http://localhost:8081/bench/{slug}/",
                "pages": [path for path, _, _ in PAGES],
                "labels": labels,
            }
        )

    dataset = {
        "version": 1,
        "generator": "benchmark/generate.py",
        "notes": (
            "Synthetic, frozen corpus: eight sites, thirteen pages each, ten planted defects per "
            "site (one per catalogued rule) and three clean pages. Findings are matched to labels "
            "by rule and page path, which is the granularity of the deterministic layer."
        ),
        "sites": sites,
        "totals": {
            "sites": len(sites),
            "pages": total_pages,
            "labels": sum(len(site["labels"]) for site in sites),
        },
    }
    dataset["digest"] = digest_of(sites)
    return dataset


def digest_of(sites: list[dict[str, Any]]) -> str:
    """The digest the eval loader computes: labels and pages only, never presentation."""
    payload = json.dumps(
        [
            {
                "slug": site["slug"],
                "pages": list(site["pages"]),
                "labels": sorted(
                    (
                        {"page": label["page"], "rule_id": label["rule_id"]}
                        for label in site["labels"]
                    ),
                    key=lambda item: (item["page"], item["rule_id"]),
                ),
            }
            for site in sites
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()[:16]}"


def _rendered() -> dict[str, str]:
    """Every page as the generator would write it, keyed by path relative to the corpus."""
    pages: dict[str, str] = {}
    for site_index, (slug, brand) in enumerate(SITES):
        for page_index, (path, title, headline) in enumerate(PAGES):
            page = Page(path=path, title=title, headline=headline)
            pages[f"{slug}/{path}"] = render(
                site_index, brand, page, defects_for(site_index, page_index)
            )
    return pages


def check() -> int:
    """Refuse a corpus that no longer matches the generator: labels would be stale."""
    expected = _rendered()
    drifted: list[str] = []
    for relative, text in expected.items():
        target = SITES_DIR / relative
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            drifted.append(relative)
    committed = json.loads(DATASET.read_text(encoding="utf-8"))
    regenerated = manifest()
    if committed != regenerated:
        # The labels are the measurement; a hand-edited manifest would make them a claim.
        drifted.append("dataset.json (manifest differs from the generator)")
    for site in committed["sites"]:
        for page in site["pages"]:
            if f"{site['slug']}/{page}" not in expected:
                drifted.append(f"{site['slug']}/{page} (orphan)")
    if drifted:
        print(f"corpus drifted from the generator: {len(drifted)} page(s)")
        for relative in drifted[:10]:
            print(f"  {relative}")
        print("run: python benchmark/generate.py")
        return 1
    print(f"corpus matches the generator: {len(expected)} pages, digest {committed['digest']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import sys

    args = sys.argv[1:] if argv is None else argv
    if "--check" in args:
        return check()
    dataset = build()
    DATASET.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {dataset['totals']['sites']} sites, {dataset['totals']['pages']} pages, "
        f"{dataset['totals']['labels']} labels, digest {dataset['digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
