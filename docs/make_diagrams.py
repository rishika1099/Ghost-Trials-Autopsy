"""Generates docs/architecture.svg and docs/snapshot.svg. Run: python3 docs/make_diagrams.py"""

from pathlib import Path

# Same visual system as the Layer Lab diagram: warm paper, one accent on the focal node,
# orthogonal connectors drawn before boxes, masked mono labels, 4px grid.
PAPER, PAPER2, SURFACE = "#f4f0e8", "#ebe4d6", "#fffdf9"
INK, MUTED, SOFT = "#1e1c19", "#6f6a62", "#8c857b"
ACCENT, ACCENT_TINT, LINK = "#b5543a", "#f6e7e0", "#3f6c8c"
SANS = "Inter, 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
HERE = Path(__file__).parent


def mono_w(text, size, track=0.06):
    return len(text) * size * (0.62 + track)


class Svg:
    def __init__(self, width, height, ident, title, desc):
        self.out = []
        self.ident = ident
        self.w(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
               f'role="img" aria-labelledby="{ident}-title {ident}-desc">')
        self.w(f'<title id="{ident}-title">{title}</title>')
        self.w(f'<desc id="{ident}-desc">{desc}</desc>')
        self.w("<defs>")
        for mid, color in (("arrow", MUTED), ("arrow-link", LINK), ("arrow-accent", ACCENT)):
            self.w(f'<marker id="{ident}-{mid}" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="8" markerHeight="8" '
                   f'markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="{color}"/></marker>')
        self.w("</defs>")
        self.w(f'<rect width="{width}" height="{height}" rx="10" fill="{PAPER}"/>')

    def w(self, s):
        self.out.append(s)

    def zone(self, x, y, wd, ht, text):
        self.w(f'<rect x="{x}" y="{y}" width="{wd}" height="{ht}" rx="8" fill="rgba(30,28,25,0.025)" '
               f'stroke="rgba(30,28,25,0.16)" stroke-width="0.8" stroke-dasharray="4,3"/>')
        self.w(f'<rect x="{x+12}" y="{y-6}" width="{mono_w(text, 7, 0.14)+8:.0f}" height="12" rx="2" fill="{PAPER}"/>')
        self.w(f'<text x="{x+16}" y="{y+3}" fill="{SOFT}" font-size="7" font-family="{MONO}" letter-spacing="0.14em">{text}</text>')

    def path(self, points, color=MUTED, dashed=False, marker="arrow"):
        d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(points))
        dash = ' stroke-dasharray="4,3"' if dashed else ""
        sw = "1" if dashed else "1.2"
        end = f' marker-end="url(#{self.ident}-{marker})"' if marker else ""
        self.w(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{dash}{end}/>')

    def label(self, text, cx=None, x=None, y=0, color=MUTED):
        width = round(mono_w(text, 8) + 8)
        width += (4 - width % 4) % 4
        left = x if x is not None else cx - width / 2
        self.w(f'<rect x="{left:.0f}" y="{y}" width="{width}" height="12" rx="2" fill="{PAPER}"/>')
        self.w(f'<text x="{left + width/2:.0f}" y="{y+9}" fill="{color}" font-size="8" font-family="{MONO}" '
               f'letter-spacing="0.06em" text-anchor="middle">{text}</text>')

    def node(self, x, y, wd, ht, tag, name, sub, fill=SURFACE, stroke=INK):
        self.w(f'<rect x="{x}" y="{y}" width="{wd}" height="{ht}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
        tw = round(mono_w(tag, 7, 0.14) + 8)
        self.w(f'<rect x="{x+12}" y="{y+10}" width="{tw}" height="12" rx="2" fill="none" stroke="{stroke}" stroke-width="0.8"/>')
        self.w(f'<text x="{x+16}" y="{y+19}" fill="{stroke}" font-size="7" font-family="{MONO}" letter-spacing="0.14em">{tag}</text>')
        self.w(f'<text x="{x+12}" y="{y+38}" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}">{name}</text>')
        self.w(f'<text x="{x+12}" y="{y+52}" fill="{MUTED}" font-size="9" font-family="{MONO}">{sub}</text>')

    def legend(self, y, items, x0=24, x1=936):
        self.w(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="rgba(30,28,25,0.12)" stroke-width="0.8"/>')
        x = x0
        for kind, fill, stroke, text in items:
            if kind == "box":
                self.w(f'<rect x="{x}" y="{y+16}" width="16" height="10" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
            else:
                self.w(f'<line x1="{x}" y1="{y+21}" x2="{x+16}" y2="{y+21}" stroke="{stroke}" stroke-width="1" stroke-dasharray="4,3"/>')
            self.w(f'<text x="{x+24}" y="{y+24}" fill="{MUTED}" font-size="8" font-family="{MONO}" letter-spacing="0.08em">{text}</text>')
            x += 24 + mono_w(text, 8, 0.08) + 28

    def save(self, name):
        self.w("</svg>")
        (HERE / name).write_text("\n".join(self.out) + "\n")
        print(f"wrote docs/{name}")


def architecture():
    s = Svg(960, 488, "gt-arch", "Ghost Trials Autopsy architecture",
            "The browser sends a question to FastAPI on Cloud Run. The Lead decides whether to clarify, refuse or research. "
            "To research, it dispatches three Researchers at once, each in a fresh context: trials, disclosures and "
            "publications. Each reads the DuckDB snapshot and calls its live APIs. Findings and gaps go back to the Lead, "
            "which can run up to three rounds. The Writer drafts a cited report from the evidence store, and the Citation "
            "Checker fixes or removes unsupported sentences. The Skeptic then reads the checked report like an editor: how strong "
            "the finding is, ordinary explanations the records can't rule out, and questions for the sponsor.")
    s.zone(576, 32, 208, 276, "ASYNCIO.GATHER · FRESH CONTEXTS")

    # Arrows first, so boxes sit on top.
    s.path([(152, 164), (196, 164)])
    s.path([(196, 180), (152, 180)], dashed=True)
    s.label("ASK", cx=174, y=146)
    s.path([(328, 164), (392, 164)])
    s.label("QUESTION", cx=360, y=146)
    s.path([(392, 180), (328, 180)], dashed=True)
    s.label("CLARIFY", cx=360, y=186)
    # Fan out: Lead to a trunk, then to each researcher.
    s.path([(536, 172), (560, 172)], marker=None)
    s.path([(560, 84), (560, 260)], marker=None)
    for cy in (84, 172, 260):
        s.path([(560, cy), (592, cy)])
    # Findings and gaps come back to the Lead.
    s.path([(592, 284), (504, 284), (504, 208)], color=ACCENT, dashed=True, marker="arrow-accent")
    s.label("FINDINGS + GAPS · ≤3 ROUNDS", x=440, y=290, color=ACCENT)
    # Live APIs.
    for cy in (84, 172, 260):
        s.path([(768, cy), (816, cy)], color=LINK, marker="arrow-link")
    s.label("LIVE", cx=792, y=66, color=LINK)
    # Snapshot.
    s.path([(680, 292), (680, 356)], dashed=True)
    s.label("ALL LANES · READ-ONLY", x=688, y=318)
    # Lead to Writer, Writer to Checker, Checker back to the app.
    s.path([(432, 204), (432, 352)])
    s.label("EVIDENCE", x=440, y=320)
    s.path([(392, 384), (336, 384)])
    s.label("DRAFT", cx=364, y=366)
    s.path([(264, 352), (264, 196)])
    s.label("CITED REPORT", x=272, y=264)
    # Checker to Skeptic, Skeptic's notes back to the app.
    s.path([(196, 384), (152, 384)])
    s.path([(88, 352), (88, 260), (232, 260), (232, 204)], dashed=True)
    s.label("EDITOR'S READ", x=96, y=300)

    s.node(24, 140, 128, 64, "BROWSER", "index.html", "trace · timeline", stroke=MUTED)
    s.node(196, 140, 132, 64, "FASTAPI", "app.py", "/chat · /run")
    s.node(392, 140, 144, 64, "LEAD", "Gate + plan", "gate · plan · gaps", fill=ACCENT_TINT, stroke=ACCENT)
    s.node(592, 52, 176, 64, "RESEARCHER", "Trials", "≤8 turns · CT.gov + SQL")
    s.node(592, 140, 176, 64, "RESEARCHER", "Disclosures", "≤8 turns · SEC tools")
    s.node(592, 228, 176, 64, "RESEARCHER", "Publications", "≤8 turns · PubMed tools")
    s.node(816, 52, 120, 64, "HTTP API", "ClinicalTrials", "+ openFDA", stroke=LINK)
    s.node(816, 140, 120, 64, "HTTP API", "SEC EDGAR", "8-K · tickers", stroke=LINK)
    s.node(816, 228, 120, 64, "HTTP API", "PubMed", "+ Europe PMC", stroke=LINK)
    s.node(592, 356, 176, 64, "DUCKDB", "Snapshot", "data/autopsy.duckdb", fill=PAPER2, stroke=MUTED)
    s.node(392, 352, 144, 64, "WRITER", "Cited report", "evidence ids only")
    s.node(196, 352, 140, 64, "CHECKER", "Citation check", "rules + model")
    s.node(24, 352, 128, 64, "SKEPTIC", "Before publish", "doubts · questions")
    s.legend(448, (("box", ACCENT_TINT, ACCENT, "FOCAL: THE LEAD"), ("box", SURFACE, INK, "AGENT / SERVICE"),
                   ("box", PAPER2, MUTED, "SNAPSHOT"), ("box", SURFACE, LINK, "EXTERNAL API"),
                   ("dash", None, MUTED, "RETURN / READ-ONLY")))
    s.save("architecture.svg")


def snapshot():
    s = Svg(960, 368, "gt-data", "Ghost Trials Autopsy snapshot",
            "scripts/build_snapshot.py pulls trials from ClinicalTrials.gov into the trials table and derives due dates, "
            "lateness and a stop-reason category. Sponsors are matched to SEC company ids, 8-K filings near each stop are "
            "pulled, and filings whose reason differs from the registry become discrepancies. PubMed and Europe PMC "
            "articles are linked to each trial by NCT ID.")
    s.zone(200, 32, 736, 280, "DATA/AUTOPSY.DUCKDB · BUILT 2026-11-05")

    s.path([(160, 84), (224, 84)], color=LINK, marker="arrow-link")
    s.path([(160, 172), (224, 172)], color=LINK, marker="arrow-link")
    s.path([(160, 260), (224, 260)], color=LINK, marker="arrow-link")
    s.path([(392, 84), (448, 84)])
    s.label("DERIVE", cx=420, y=66)
    s.path([(308, 116), (308, 140)], dashed=True)
    s.label("SPONSOR NAME", x=316, y=122)
    s.path([(392, 172), (448, 172)])
    s.label("±120 DAYS", cx=420, y=154)
    s.path([(616, 172), (672, 172)])
    s.path([(532, 116), (532, 140)], dashed=True)
    s.label("STOP DATE + REASON", x=540, y=122)
    s.path([(308, 228), (308, 204)], dashed=True)
    s.label("NCT ID", x=316, y=210)
    s.label("COMPARE", cx=644, y=154)

    s.node(24, 52, 136, 64, "API v2", "ClinicalTrials.gov", "industry ph 2/3", stroke=LINK)
    s.node(24, 140, 136, 64, "SEC", "EDGAR", "tickers · 8-K text", stroke=LINK)
    s.node(24, 228, 136, 64, "NCBI + EBI", "PubMed", "+ Europe PMC", stroke=LINK)
    s.node(224, 52, 168, 64, "TABLE", "trials · 16,473", "status · reason · dates")
    s.node(448, 52, 168, 64, "TABLE", "trial_derived", "due · days late · reason")
    s.node(224, 140, 168, 64, "TABLE", "sponsor_cik · 591", "fuzzy match ≥ threshold")
    s.node(448, 140, 168, 64, "TABLE", "filings · 2,053", "8-K near each stop")
    s.node(672, 140, 248, 64, "TABLE", "discrepancies · 1,564", "7 checked by hand", fill=ACCENT_TINT, stroke=ACCENT)
    s.node(224, 228, 168, 64, "TABLE", "publications · 26,154", "9,758 trials linked")
    s.node(672, 52, 248, 64, "TABLE", "snapshot_meta", "build date · row counts", fill=PAPER2, stroke=MUTED)
    s.legend(328, (("box", ACCENT_TINT, ACCENT, "FOCAL: THE JOIN NO ONE ELSE HAS"), ("box", SURFACE, INK, "TABLE"),
                   ("box", SURFACE, LINK, "SOURCE API"), ("dash", None, MUTED, "JOIN KEY")))
    s.save("snapshot.svg")


if __name__ == "__main__":
    architecture()
    snapshot()
