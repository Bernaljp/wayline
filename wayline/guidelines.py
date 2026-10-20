"""Venue guidelines (Implementation Decisions 13): building `guidelines/<venue>/` and the seven checks.

Two halves, and the whole point of the module is the line between them. The first half builds
`guidelines/<venue>/guidelines.json` for the fifteen venues `research-notes/10` recorded: the
fields are the note's, transcribed here, and the build fetches each venue's pages through the
fetch seam to say whether they can still be believed. The second half is the seven mechanical
checks a writer runs on a draft, and they read `guidelines.json` and nothing else: no research
note, no model call, no network.

**What the build verifies, and what it cannot.** Nothing here extracts a word count out of
HTML. Fifteen publisher layouts would need fifteen parsers and each one would rot. Instead
every field carries the short strings the note read it off (`evidence`), and the build re-fetches
the page and looks for them. A field is `fully_verified` only when the note verified it, its
pages were reached, and every one of its strings is still there. Everything else lands in
`unverified_fields`, by the precise sub-path where the note was partial (`figure_spec.color_mode`),
and `source.md` says which of the three reasons applies: the note never confirmed it, the page
was unreachable, or the page no longer carries the wording. A field whose evidence lives in a
PDF the build does not read keeps the note's verdict and `source.md` says so plainly.

**What a stateless client can reach.** Four of the fifteen venues sit behind a bot check that
answers a plain `urllib` request with 403: Cell, Cell Systems, PNAS, and Bioinformatics. The note
reached three of them through a browser-shaped fallback the harness does not have, so their
fields arrive here already recorded and leave the build unverified. Cell and Genome Biology are
retried with the alternate paths the note's action items name; Genome Biology's retry is the one
that pays, because BMC has since moved to Springer Nature Link and the article-type page answers.

**What is never stored.** Manuscript templates are linked, never written to disk: `template.url`
is a link and no code path fetches it. `checklist/` holds reporting-checklist forms only, and
only the ones a venue publishes without a login.

Three fields the spec's list does not name are here because a check it asks for cannot run
without them: `length_limits.excluded_sections` (a word count "with the venue's exclusions" needs
to know them), `reference_style.citation` (prose cannot drive a style check), and
`template.document_class` (the conformance check compares a draft's class or style file against
it). `figure_spec.notes` carries the figure facts that are neither a count, a format, a
resolution, a colour mode, nor a size, the way `length_limits.notes` carries the same for length.
"""

import argparse
import gzip
import html
import json
import re
import sys
from collections import namedtuple
from copy import deepcopy
from datetime import date
from pathlib import Path

from wayline import HARNESS_ROOT
from wayline.cli import parse_args
from wayline.fetch import FetchError, Fetcher, recording_fetcher
from wayline.jsonschema import check, load_schema
from wayline.provenance import identifier_index, manifest_paths, parse_tag, read_manifest, ref_slug, sentences, strip_tags

__all__ = [
    "GuidelinesError", "GUIDELINES_DIR", "GUIDELINES_JSON", "SOURCE_MD", "CHECKLIST_DIR",
    "NOTE", "NOTE_DATE", "VENUES", "VERIFIED_FIELDS", "STUDY_TYPES", "CHECKS",
    "venue_seed", "build", "build_venue", "read_guidelines", "render_source",
    "Manuscript", "Finding", "run_checks", "worst", "check_length", "check_structure", "check_figures",
    "check_references", "check_reporting_checklists", "check_template", "check_provenance",
    "image_facts", "page_text", "build_command",
]

GUIDELINES_DIR = "guidelines"
GUIDELINES_JSON = "guidelines.json"
SOURCE_MD = "source.md"
CHECKLIST_DIR = "checklist"

# Where the fields come from, and the day that note was written. A venue whose page the build
# cannot reach keeps this date rather than claiming the build's.
NOTE = "research-notes/10-venue-guidelines-sources.md"
NOTE_DATE = "2026-09-11"

# The eight fields verification speaks about; `structure_flexible` rides with `required_structure`.
VERIFIED_FIELDS = (
    "length_limits", "required_structure", "figure_spec", "reference_style",
    "reporting_checklists", "submission_steps", "template", "license_of_summary_source",
)

# The study types a reporting checklist is asked for, and the words in a draft that say so. The
# detection is the keyword heuristic research-notes 10 proposes for check 5; a cheap
# classification call could replace it without changing anything else here.
STUDY_TYPES = {
    "animal": ("mouse", "mice", "rat ", "rats", "zebrafish", "in vivo", "animal experiment", "animals were"),
    "clinical-trial": ("randomized controlled", "randomised controlled", "clinical trial", "trial registration", "nct0"),
    "systematic-review": ("systematic review", "meta-analysis", "meta analysis"),
    "observational": ("cohort study", "case-control", "cross-sectional", "observational study"),
    "diagnostic-accuracy": ("diagnostic accuracy", "sensitivity and specificity", "roc curve"),
    "microarray": ("microarray", "gene expression omnibus", "geo accession"),
    "mendelian-randomisation": ("mendelian randomization", "mendelian randomisation"),
    "qualitative": ("semi-structured interview", "focus group", "thematic analysis"),
    "life-sciences": ("cell line", "antibod", "sequencing", "rna-seq", "western blot", "flow cytometry"),
    "behavioural": ("participants were recruited", "informed consent", "questionnaire"),
    "custom-code": ("custom code", "code availability", "source code is available"),
}

# The seven checks, in the order research-notes 10 numbers them.
CHECKS = ("length", "structure", "figures", "references", "reporting_checklists", "template", "provenance")


class GuidelinesError(ValueError):
    """A venue nobody recorded, a guidelines file that is not one, or a manuscript with no text."""


# --- the fifteen venues -------------------------------------------------------------------------
#
# Transcribed from `research-notes/10-venue-guidelines-sources.md`, one entry per venue in the
# order the note's table lists them. `sources` are fetched at build time, primary first; an
# `alternates` list is tried in order when the URL before it does not answer. `provides` names the
# fields a source stands behind, so an unreachable page unverifies exactly its own fields.
# `evidence` is the wording the note read a field off, matched against the fetched text.
# `unverified` is what the note itself could not confirm, at whatever depth it could not.

VENUES = (
    {
        "venue": "nature",
        "display_name": "Nature",
        "sources": (
            {
                "url": "https://www.nature.com/nature/for-authors/formatting-guide",
                "provides": VERIFIED_FIELDS,
            },
        ),
        "evidence": {
            "length_limits": ("4300 words", "2,500 words", "3,000 words"),
            "reference_style": ("50 references",),
            "figure_spec": ("90 mm", "180 mm", "170 mm"),
            "reporting_checklists": ("reporting summary",),
            "submission_steps": ("30 mb",),
        },
        "unverified": ("figure_spec.color_mode", "submission_steps"),
        "caveats": (
            "nature.com redirects a stateless request through a cookie-consent check and answers with "
            "`?error=cookies_not_supported` on the URL; the page behind it is the real formatting guide, "
            "which is why the build treats it as reached.",
            "The page says 4300 words without a thousands separator, where the note wrote 4,300; the "
            "evidence string is the page's spelling.",
            "The submission portal is not named on the page, so `submission_steps` records only what the "
            "page states and stays unverified.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": 4300,
                "page_count": 8,
                "abstract_word_count": 200,
                "notes": "A typical 8-page biological, clinical or social-sciences Article is about 4300 words with 5-6 display items; a 6-page physical-sciences Article about 2,500 words with 4. The Methods section does not typically exceed 3,000 words. The opening summary paragraph is up to 200 words.",
                "excluded_sections": ["Methods", "References", "Figure legends", "Extended Data", "Supplementary Information"],
            },
            "required_structure": [
                "Title", "Authors", "Affiliations", "Summary paragraph", "Main text", "References",
                "Tables", "Figure legends", "Methods", "Acknowledgements", "Funding statement",
                "Author contributions", "Competing interests", "Additional information",
            ],
            "structure_flexible": True,
            "figure_spec": {
                "max_count": 6,
                "formats": [],
                "min_dpi": None,
                "max_dpi": None,
                "color_mode": [],
                "max_file_size_mb": None,
                "legend_max_words": None,
                "notes": "Standard figure sizes are 90 mm (single column) and 180 mm (double column); the full depth of the page is 170 mm. JPEGs are acceptable at initial submission and high-resolution files are required only on acceptance. Extended Data is capped at 10 display items.",
            },
            "reference_style": {
                "style": "Numbered, superscript in the text; surname and initials, journal title italic and abbreviated, volume bold.",
                "max_count": 50,
                "citation": "numbered",
            },
            "reporting_checklists": [
                {
                    "name": "Reporting Summary",
                    "required": True,
                    "study_types": ["life-sciences", "behavioural"],
                    "url": "https://www.nature.com/documents/nr-reporting-summary-flat.pdf",
                    "cache_as": "nature-reporting-summary.pdf",
                },
            ],
            "submission_steps": [
                "submit through the online system as a single Word or PDF file of up to 30 MB",
                "figures may be placed in the text at initial submission",
                "supply high-resolution figures only on acceptance",
            ],
            "template": {
                "latex_or_word_no_login": True,
                "url": "https://www.springernature.com/gp/authors/campaigns/latex-author-support/see-where-our-services-will-take-you/18782940",
                "notes": "There is no Nature-specific manuscript template; the journal is format-flexible at submission by design. The link is the generic Springer Nature LaTeX and Word package, downloadable without a login.",
                "document_class": None,
            },
            "license_of_summary_source": {
                "statement": "(c) 2026 Springer Nature Limited; the page links nature.com's Terms and Conditions.",
                "url": "https://www.nature.com/info/terms-and-conditions",
            },
        },
    },
    {
        "venue": "nature-methods",
        "display_name": "Nature Methods",
        "sources": (
            {
                "url": "https://www.nature.com/nmeth/submission-guidelines",
                "provides": ("submission_steps", "license_of_summary_source"),
            },
            {
                "url": "https://www.nature.com/nmeth/submission-guidelines/preparing-your-submission",
                "provides": ("required_structure", "template"),
            },
            {
                "url": "https://www.nature.com/nmeth/content",
                "provides": ("length_limits", "figure_spec", "reference_style", "reporting_checklists"),
            },
        ),
        "evidence": {
            "length_limits": ("3,000 words", "5,000 words", "150 words"),
            "required_structure": ("online methods", "extended data"),
        },
        "unverified": (
            "figure_spec.formats", "figure_spec.min_dpi", "figure_spec.color_mode",
            "reporting_checklists", "template",
        ),
        "caveats": (
            "The submission-guidelines page is a hub; the length and display-item numbers are on "
            "https://www.nature.com/nmeth/content and the file list on the preparing-your-submission page, "
            "so the build fetches all three.",
            "The Nature Portfolio Reporting Summary is standard across Nature-branded journals, but no "
            "nmeth-specific page saying so was fetched, so `reporting_checklists` stays unverified for this journal.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": 3000,
                "page_count": None,
                "abstract_word_count": 150,
                "notes": "Main text 3,000 words, up to 5,000 with editorial discretion, excluding abstract, Methods, references and figure legends. The abstract is up to 150 words and unreferenced. About 50 references is guidance rather than a cap.",
                "excluded_sections": ["Abstract", "Methods", "Online Methods", "References", "Figure legends"],
            },
            "required_structure": [
                "Title", "Authors", "Abstract", "Introduction", "Results", "Discussion", "Online Methods",
            ],
            "structure_flexible": False,
            "figure_spec": {
                "max_count": 6,
                "formats": [],
                "min_dpi": None,
                "max_dpi": None,
                "color_mode": [],
                "max_file_size_mb": None,
                "legend_max_words": None,
                "notes": "Up to 6 figures and tables together in an Article; Extended Data is optional and capped at 10 items. Resolution, format and colour mode are not stated on the pages fetched.",
            },
            "reference_style": {
                "style": "Numbered, Nature Portfolio house style; about 50 references as guidance.",
                "max_count": None,
                "citation": "numbered",
            },
            "reporting_checklists": [
                {
                    "name": "Reporting Summary",
                    "required": True,
                    "study_types": ["life-sciences", "behavioural"],
                    "url": "https://www.nature.com/documents/nr-reporting-summary-flat.pdf",
                    "cache_as": "nature-reporting-summary.pdf",
                },
            ],
            "submission_steps": [
                "submit through the Manuscript Tracking System at https://mts-nmeth.nature.com/, which requires an account",
                "supply a cover letter explaining the advance",
            ],
            "template": {
                "latex_or_word_no_login": None,
                "url": None,
                "notes": "No Nature Methods template was found on the journal's own pages.",
                "document_class": None,
            },
            "license_of_summary_source": {
                "statement": "(c) 2026 Springer Nature Limited, under the nature.com Terms and Conditions.",
                "url": "https://www.nature.com/info/terms-and-conditions",
            },
        },
    },
    {
        "venue": "nature-communications",
        "display_name": "Nature Communications",
        "sources": (
            {
                "url": "https://www.nature.com/ncomms/submit/guide-to-authors",
                "provides": VERIFIED_FIELDS,
            },
        ),
        "evidence": {},
        "unverified": (
            "length_limits", "required_structure", "figure_spec", "reference_style",
            "reporting_checklists", "submission_steps",
        ),
        "unverified_reasons": dict.fromkeys(
            ("length_limits", "required_structure", "figure_spec", "reference_style",
             "reporting_checklists", "submission_steps"),
            "the note read it off the submission-guide PDF the page links, and nothing here reads inside a PDF",
        ),
        "caveats": (
            "The guide-to-authors page is prose and links https://www.nature.com/documents/ncomms-submission-guide.pdf, "
            "which is where every number below was read. The build fetches the page, never the PDF: nothing here reads "
            "inside a PDF, so those fields stay unverified however good the note's own reading of them was.",
            "The PDF's own revision stamp reads May 2019 while the page linking it is current.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": 5000,
                "page_count": None,
                "abstract_word_count": 150,
                "notes": "Main text up to 5,000 words, Methods typically under 3,000, abstract about 150 words and unreferenced, title up to 15 words. Up to 70 references as a guideline.",
                "excluded_sections": ["Abstract", "Methods", "References", "Figure legends"],
            },
            "required_structure": [
                "Title", "Authors", "Abstract", "Results", "Methods", "Data availability",
                "Code availability", "References", "Acknowledgements", "Author contributions",
                "Competing interests", "Materials and Correspondence", "Tables", "Figures",
            ],
            "structure_flexible": False,
            "figure_spec": {
                "max_count": 10,
                "formats": ["AI", "EPS", "PDF", "PS", "SVG", "PSD", "TIF", "PNG", "JPG"],
                "min_dpi": 300,
                "max_dpi": None,
                "color_mode": ["RGB"],
                "max_file_size_mb": None,
                "legend_max_words": 350,
                "notes": "Up to 10 display items, figures and tables together. Arial or Helvetica; avoid red-green contrast and rainbow scales in favour of colourblind-safe palettes. High resolution is not required at initial submission.",
            },
            "reference_style": {
                "style": "Numbered, one publication per reference number, each carrying the cited title.",
                "max_count": 70,
                "citation": "numbered",
            },
            "reporting_checklists": [
                {
                    "name": "Reporting Summary",
                    "required": True,
                    "study_types": ["life-sciences", "behavioural"],
                    "url": "https://www.nature.com/documents/nr-reporting-summary-flat.pdf",
                    "cache_as": "nature-reporting-summary.pdf",
                },
                {"name": "Editorial policy checklist", "required": True, "study_types": [], "url": None, "cache_as": None},
                {"name": "Code and software submission checklist", "required": False, "study_types": ["custom-code"], "url": None, "cache_as": None},
            ],
            "submission_steps": [
                "submit through the Manuscript Tracking System at https://mts-ncomms.nature.com/, which requires an account",
                "a cover letter is optional and is used only for information not shared with referees",
                "open the checklist forms in Adobe Reader so their fields are fillable",
            ],
            "template": {
                "latex_or_word_no_login": True,
                "url": "https://www.springernature.com/gp/authors/campaigns/latex-author-support/see-where-our-services-will-take-you/18782940",
                "notes": "No Nature Communications template exists; the generic Springer Nature package is the only no-login option.",
                "document_class": None,
            },
            "license_of_summary_source": {
                "statement": "(c) 2026 Springer Nature Limited; the journal's own articles have been open access under CC BY 4.0 since January 2016.",
                "url": "https://www.nature.com/info/terms-and-conditions",
            },
        },
    },
    {
        "venue": "cell",
        "display_name": "Cell",
        "sources": (
            {
                "url": "https://www.cell.com/cell/information-for-authors",
                "alternates": (
                    "https://www.cell.com/cell/authors",
                    "https://www.cell.com/information-for-authors/figure-guidelines",
                ),
                "provides": VERIFIED_FIELDS,
            },
        ),
        "evidence": {},
        "unverified": VERIFIED_FIELDS,
        "unverified_reasons": dict.fromkeys(
            VERIFIED_FIELDS,
            "the note's value is a search-result snippet of the live page, not a fetch of it",
        ),
        "caveats": (
            "cell.com answers a stateless request with HTTP 403 on every path tried, the note's included, so every "
            "field below is a search-result snippet of the live page rather than a fetch. The alternates the note's "
            "action item suggests are retried at build time and are refused the same way.",
            "Cell Press's site-wide figure guidelines and article templates almost certainly apply to Cell as well as "
            "to Cell Systems, but that is an inference from a sister journal's pages and is not recorded here as Cell's.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": 7000,
                "page_count": None,
                "abstract_word_count": None,
                "notes": "Articles are capped at 7,000 words including main figure legends but excluding STAR Methods text, supplemental legends and references.",
                "excluded_sections": ["STAR Methods", "References", "Supplemental information"],
            },
            "required_structure": ["Title", "Authors", "Summary", "Introduction", "Results", "Discussion", "STAR Methods", "References"],
            "structure_flexible": True,
            "figure_spec": {
                "max_count": 7,
                "formats": [],
                "min_dpi": None,
                "max_dpi": None,
                "color_mode": [],
                "max_file_size_mb": None,
                "legend_max_words": None,
                "notes": "No more than 7 figures and tables together. Resolution, format and colour mode did not surface in any snippet.",
            },
            "reference_style": {
                "style": "Cell Press house style since October 2022: numbered, superscript in the text, 'et al.' only after 10 authors.",
                "max_count": None,
                "citation": "numbered",
            },
            "reporting_checklists": [],
            "submission_steps": [
                "an optional presubmission inquiry to cellms@cell.com",
                "or the Cell Press Multi-Journal Submission for cross-journal consideration",
                "formatting need not be finalised at initial submission",
            ],
            "template": {
                "latex_or_word_no_login": None,
                "url": None,
                "notes": "Unverified: both candidate pages were unreachable.",
                "document_class": None,
            },
            "license_of_summary_source": {
                "statement": "Copyright (c) 2026 Elsevier Inc., its licensors and contributors, reserving text and data mining and AI training rights; the Terms and Conditions permit personal, non-commercial download only.",
                "url": "https://www.cell.com/terms-and-conditions",
            },
        },
    },
    {
        "venue": "cell-systems",
        "display_name": "Cell Systems",
        "sources": (
            {
                "url": "https://www.cell.com/cell-systems/information-for-authors",
                "alternates": ("https://www.cell.com/information-for-authors/figure-guidelines",),
                "provides": VERIFIED_FIELDS,
            },
        ),
        "evidence": {},
        "unverified": (),
        "caveats": (
            "The note reached these pages through a browser-shaped fallback after a Cloudflare challenge; the harness's "
            "own client is refused with HTTP 403, so the build cannot re-confirm any of it and every field is unverified "
            "for as long as that holds.",
            "The figure and template facts are from the site-wide Cell Press pages, which apply to every Cell Press journal.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": None,
                "page_count": None,
                "abstract_word_count": 150,
                "notes": "No explicit word cap: long enough to convey the work, short enough to read in one sitting. Title up to about 145 characters, summary up to 150 words. Figure and table counts by article type: Articles 7, Reports 4, Brief Reports 2, Methods 7, Methods in Brief 2.",
                "excluded_sections": ["STAR Methods", "References", "Supplemental information"],
            },
            "required_structure": [
                "Title", "Authors", "Affiliations", "Contact information", "Summary", "Keywords",
                "Introduction", "Results", "Discussion", "Resource availability", "Acknowledgments",
                "Author contributions", "Declaration of interests", "Supplemental information",
                "Figure titles and legends", "Tables", "STAR Methods", "References",
            ],
            "structure_flexible": False,
            "figure_spec": {
                "max_count": 7,
                "formats": ["TIFF", "PDF", "EPS", "JPEG"],
                "min_dpi": 300,
                "max_dpi": None,
                "color_mode": ["RGB"],
                "max_file_size_mb": 20,
                "legend_max_words": None,
                "notes": "Colour and greyscale at 300 dpi, black and white at 500 dpi, line art at 1,000 dpi, all at final print size. Arial, fonts embedded.",
            },
            "reference_style": {
                "style": "Numbered in order of first citation, superscript in the text; 'et al.' only after 10 authors.",
                "max_count": None,
                "citation": "numbered",
            },
            "reporting_checklists": [
                {"name": "Cell Press reporting checklists", "required": False, "study_types": [], "url": None, "cache_as": None},
                {"name": "ARRIVE", "required": False, "study_types": ["animal"], "url": None, "cache_as": None},
                {"name": "Clinical trial checklist", "required": False, "study_types": ["clinical-trial"], "url": None, "cache_as": None},
            ],
            "submission_steps": [
                "submit through Editorial Manager at editorialmanager.com/cell-systems",
                "initial submission as a PDF, or Word plus separate files; LaTeX needs an accompanying PDF",
                "keep files to 1-2 MB each and 20 MB in total",
                "a cover letter is required: background, conceptual advance, significance, consortium status, reviewer suggestions",
                "the Cell Press Multi-Journal Submission option is available",
            ],
            "template": {
                "latex_or_word_no_login": True,
                "url": "https://www.cell.com/information-for-authors/article-templates",
                "notes": "Word templates and a Cell Press LaTeX zip (.tex, .bib, .bst, .sty) download without a login. Linked, never stored.",
                "document_class": None,
            },
            "license_of_summary_source": {
                "statement": "Copyright (c) 2026 Elsevier Inc., its licensors and contributors.",
                "url": "https://www.cell.com/terms-and-conditions",
            },
        },
    },
    {
        "venue": "pnas",
        "display_name": "PNAS",
        "sources": (
            {
                "url": "https://www.pnas.org/author-center/submitting-your-manuscript",
                "alternates": ("https://www.pnas.org/author-center",),
                "provides": VERIFIED_FIELDS,
            },
        ),
        "evidence": {},
        "unverified": ("submission_steps.cover_letter",),
        "caveats": (
            "pnas.org answers the harness's client with HTTP 403 behind a Cloudflare challenge, so the build cannot "
            "re-confirm the note's browser-shaped fetch and every field is unverified until it can.",
            "Whether a cover letter is required was not stated on the pages the note read.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": 4000,
                "page_count": 6,
                "abstract_word_count": 250,
                "notes": "Research Reports are preferred at 6 pages, about 4,000 words with about 50 references and 4 medium graphical elements, and capped at 12. Brief Reports are 3 pages, about 1,600 words and up to 15 references. The significance statement is up to 120 words.",
                "excluded_sections": ["References", "Acknowledgments", "Figure legends"],
            },
            "required_structure": [
                "Title page", "Abstract", "Significance statement", "Introduction", "Results",
                "Discussion", "Materials and Methods", "Acknowledgments", "References", "Figure legends",
            ],
            "structure_flexible": False,
            "figure_spec": {
                "max_count": None,
                "formats": ["TIFF", "EPS", "PDF", "PPT"],
                "min_dpi": 300,
                "max_dpi": 1200,
                "color_mode": ["RGB"],
                "max_file_size_mb": None,
                "legend_max_words": None,
                "notes": "Size classes: small about 9x6 cm, medium about 11x11 cm, large about 18x22 cm. Raster at 300 ppi without text, 600-900 with text, 1,000-1,200 for line art. 3D figures as PRC or U3D.",
            },
            "reference_style": {
                "style": "Numbered in order of first citation, following the CSE Manual (8th edition); more than five authors are listed as the first author and 'et al.'; the LaTeX bibliography style is pnas-new.bst.",
                "max_count": None,
                "citation": "numbered",
            },
            "reporting_checklists": [
                {"name": "ARRIVE", "required": True, "study_types": ["animal"], "url": None, "cache_as": None},
                {"name": "MIAME", "required": True, "study_types": ["microarray"], "url": None, "cache_as": None},
            ],
            "submission_steps": [
                "submit through PNAS's own tracking system at https://www.pnascentral.org/cgi-bin/main.plex; no email submissions",
                "the journal is format-neutral at initial submission",
                "supply a data-sharing plan and funding information",
                "suggest at least three reviewers, Editorial Board members or NAS members",
            ],
            "template": {
                "latex_or_word_no_login": True,
                "url": "https://www.pnas.org/pb-assets/authors/PNASTemplateforMainManuscript-1755285180130.docx",
                "notes": "Word templates for the research article, Brief Report and SI Appendix, and LaTeX templates with a class, style and bibliography file plus Overleaf versions, all reachable without a login from the author centre; the URL is the main-manuscript Word file. Linked, never stored.",
                "document_class": "pnas-new",
            },
            "license_of_summary_source": {
                "statement": "Copyright (c) 2026 National Academy of Sciences; the page links its Terms and Privacy Policy.",
                "url": "https://www.pnas.org/author-center/submitting-your-manuscript",
            },
        },
    },
    {
        "venue": "plos-compbiol",
        "display_name": "PLOS Computational Biology",
        "sources": (
            {
                "url": "https://journals.plos.org/ploscompbiol/s/submission-guidelines",
                "provides": ("length_limits", "required_structure", "reference_style", "reporting_checklists", "submission_steps", "template", "license_of_summary_source"),
            },
            {
                "url": "https://journals.plos.org/ploscompbiol/s/figures",
                "provides": ("figure_spec",),
            },
        ),
        "evidence": {
            "length_limits": ("no restrictions on word count", "300 words"),
            "reference_style": ("vancouver",),
            "reporting_checklists": ("prisma", "arrive", "strobe", "consort checklist"),
            "figure_spec": ("tiff or eps", "2625 pixels", "rgb (8 bit/channel)", "10 mb"),
        },
        "unverified": ("template", "license_of_summary_source"),
        "caveats": (
            "The only template-shaped files PLOS links are sample formatting PDFs, not a fillable Word or LaTeX "
            "manuscript template, so `template` records their absence rather than a confirmed no.",
            "The page's exact CC BY footer wording was not captured, so the licence statement is a summary rather than a quotation.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": None,
                "page_count": None,
                "abstract_word_count": 300,
                "notes": "Manuscripts can be any length: no restriction on word count, figure count or supporting information. Software articles are under 3,500 words. The author summary is 150 to 200 words.",
                "excluded_sections": [],
            },
            "required_structure": [
                "Title", "Authors", "Affiliations", "Abstract", "Author summary", "Introduction",
                "Results", "Discussion", "Materials and Methods", "Acknowledgments", "References",
                "Supporting Information captions",
            ],
            "structure_flexible": False,
            "figure_spec": {
                "max_count": None,
                "formats": ["TIFF", "EPS"],
                "min_dpi": 300,
                "max_dpi": 600,
                "color_mode": ["RGB", "grayscale"],
                "max_file_size_mb": 10,
                "legend_max_words": None,
                "notes": "Width 789 to 2,250 pixels and height at most 2,625 pixels, both at 300 dpi. Text inside a figure is Arial, Times or Symbol at 8 to 12 point. A two-point white-space border around the figure.",
            },
            "reference_style": {
                "style": "Vancouver (ICMJE), numbered in citation-sequence order, in-text numbers in square brackets, first six authors then 'et al.'.",
                "max_count": None,
                "citation": "numbered",
            },
            "reporting_checklists": [
                {"name": "ARRIVE", "required": True, "study_types": ["animal"], "url": None, "cache_as": None},
                {"name": "CONSORT", "required": True, "study_types": ["clinical-trial"], "url": None, "cache_as": None},
                {"name": "TIDieR", "required": True, "study_types": ["clinical-trial"], "url": None, "cache_as": None},
                {"name": "PRISMA", "required": True, "study_types": ["systematic-review"], "url": None, "cache_as": None},
                {"name": "STROBE", "required": True, "study_types": ["observational"], "url": None, "cache_as": None},
                {"name": "STARD", "required": True, "study_types": ["diagnostic-accuracy"], "url": None, "cache_as": None},
                {"name": "MIAME", "required": True, "study_types": ["microarray"], "url": None, "cache_as": None},
                {"name": "STROBE-MR", "required": True, "study_types": ["mendelian-randomisation"], "url": None, "cache_as": None},
                {"name": "COREQ", "required": True, "study_types": ["qualitative"], "url": None, "cache_as": None},
            ],
            "submission_steps": [
                "submit one compiled PDF of text and figures at initial submission",
                "upload the cover letter separately, addressing suitability and impact",
                "suggest at least four potential reviewers and, if you wish, an Academic Editor",
                "a bioRxiv direct transfer is available",
            ],
            "template": {
                "latex_or_word_no_login": False,
                "url": None,
                "notes": "Sample formatting PDFs are linked without a login, but no fillable Word or LaTeX manuscript template was found.",
                "document_class": None,
            },
            "license_of_summary_source": {
                "statement": "PLOS is a nonprofit 501(c)(3) corporation; the page links its Privacy Policy and Terms of Use and references the CC BY licensing policy, whose exact footer wording was not captured.",
                "url": "https://journals.plos.org/ploscompbiol/s/submission-guidelines",
            },
        },
    },
    {
        "venue": "elife",
        "display_name": "eLife",
        "sources": (
            {
                "url": "https://elife-rp.msubmit.net/html/elife-rp_author_instructions.html",
                "provides": VERIFIED_FIELDS,
            },
        ),
        "evidence": {
            "length_limits": ("5,000 words", "1,500 words"),
            "figure_spec": ("300 dpi", "10cm", "rgb"),
            "reference_style": ("apa",),
            "reporting_checklists": ("mdar",),
        },
        "unverified": ("license_of_summary_source",),
        "caveats": (
            "The Author Guide is served from eLife's submission platform and fetches with no login.",
            "The page carries the platform's own software notice rather than a licence for its text, so the licence field "
            "records eLife's Terms and Conditions and the CC BY 4.0 its articles carry, not a licence for the guide itself.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": 5000,
                "page_count": None,
                "abstract_word_count": None,
                "notes": "Research Articles have no maximum, but authors are asked to stay under 5,000 words of main text, excluding Materials and Methods, references and figure legends, with no limit on display items. Short Reports are 1,500 words with 3 to 4 display items; Review Articles up to about 10,000 words; Feature Articles under 2,000 words with up to 20 references.",
                "excluded_sections": ["Materials and Methods", "Methods", "References", "Figure legends"],
            },
            "required_structure": [
                "Introduction", "Results", "Discussion", "Materials and Methods", "Acknowledgements",
                "References", "Figures", "Tables",
            ],
            "structure_flexible": True,
            "figure_spec": {
                "max_count": None,
                "formats": [],
                "min_dpi": 300,
                "max_dpi": None,
                "color_mode": ["RGB"],
                "max_file_size_mb": None,
                "legend_max_words": None,
                "notes": "Minimum physical width 10 cm, or 20 cm for a full-page-width figure, both at 300 dpi. No multi-page figures and no figure supplements. Minimise whitespace; Colour Universal Design principles are recommended.",
            },
            "reference_style": {
                "style": "Any reference style is accepted and reformatted in production; APA is the closest match to eLife's own. DOIs are requested where possible.",
                "max_count": None,
                "citation": "any",
            },
            "reporting_checklists": [
                {
                    "name": "MDAR",
                    "required": True,
                    "study_types": [],
                    "url": "https://elife-cdn.s3.amazonaws.com/xpub/guides/eLife_MDAR_checklist.pdf",
                    "cache_as": "elife-mdar-checklist.pdf",
                },
                {"name": "Key Resources Table", "required": False, "study_types": ["life-sciences"], "url": None, "cache_as": None},
                {"name": "Inclusion in Global Research form", "required": False, "study_types": [], "url": None, "cache_as": None},
            ],
            "submission_steps": [
                "submit directly, or transfer a preprint from bioRxiv or medRxiv, or come through Review Commons",
                "eLife reviews the preprint and publishes a Reviewed Preprint with an assessment and public reviews rather than accepting or rejecting",
                "request a Version of Record later if you want one",
                "a cover letter is required for Review Articles and Replication Studies and for disclosing data-sharing exceptions or preregistration",
                "the publishing fee was $3,750 as of July 2026, with waivers",
            ],
            "template": {
                "latex_or_word_no_login": True,
                "url": "https://elife-cdn.s3.amazonaws.com/author-guide/elife-latex-template.zip",
                "notes": "A LaTeX template zip downloads without a login; DOCX and RTF are also accepted. Linked, never stored.",
                "document_class": "elife",
            },
            "license_of_summary_source": {
                "statement": "The guide is hosted on eLife's submission platform, whose footer carries a software notice rather than a content licence; eLife's own Terms and Conditions apply and its articles are CC BY 4.0.",
                "url": "https://elifesciences.org/terms",
            },
        },
    },
    {
        "venue": "bioinformatics",
        "display_name": "Bioinformatics (Oxford University Press)",
        "sources": (
            {
                "url": "https://academic.oup.com/bioinformatics/pages/author-guidelines",
                "alternates": ("https://academic.oup.com/bioinformatics/pages/General_Instructions",),
                "provides": VERIFIED_FIELDS,
            },
        ),
        "evidence": {},
        "unverified": ("figure_spec", "reference_style", "template"),
        "caveats": (
            "academic.oup.com answers the harness's client with HTTP 403 behind a bot check, on the author-guidelines page "
            "and on the General Instructions page the note also read, so nothing below is re-confirmed by the build.",
            "The guidelines mention 'the journal template' without a no-login download link, so `template` stays unverified.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": 5000,
                "page_count": 7,
                "abstract_word_count": None,
                "notes": "Original Papers up to 7 pages, about 5,000 words excluding figures. Application Notes up to 4 pages, about 2,600 words, or 2,000 words plus one figure. Reviews 3 to 8 pages. A manuscript 20 percent or more over its limit is typically returned without review.",
                "excluded_sections": ["References", "Figure legends"],
            },
            "required_structure": ["Availability and implementation", "Data availability"],
            "structure_flexible": True,
            "figure_spec": {
                "max_count": None,
                "formats": [],
                "min_dpi": None,
                "max_dpi": None,
                "color_mode": [],
                "max_file_size_mb": None,
                "legend_max_words": None,
                "notes": "No figure count, resolution, format or colour-mode requirement was found on the pages fetched.",
            },
            "reference_style": {
                "style": "Not stated on the pages fetched; only dataset citations are specified, following the DataCite recommendations.",
                "max_count": None,
                "citation": "unknown",
            },
            "reporting_checklists": [],
            "submission_steps": [
                "submit through ScholarOne at http://mc.manuscriptcentral.com/bioinformatics, which requires an account",
                "a cover letter is mandatory and must justify the fit, disclose related publications and preprints, and say how this differs from them",
                "machine-learning papers need a subsection describing the composition of the training dataset",
                "software papers need an Availability and Implementation section",
                "every paper needs a data availability statement",
            ],
            "template": {
                "latex_or_word_no_login": None,
                "url": None,
                "notes": "The guidelines reference a journal template and accept Word or LaTeX on acceptance, but no direct no-login download link was found.",
                "document_class": None,
            },
            "license_of_summary_source": {
                "statement": "The page states that published papers are made available under CC BY through open-access agreements; that is a publishing licence, not a statement about reusing the guidelines text.",
                "url": "https://academic.oup.com/bioinformatics/pages/author-guidelines",
            },
        },
    },
    {
        "venue": "genome-biology",
        "display_name": "Genome Biology",
        "sources": (
            {
                "url": "https://genomebiology.biomedcentral.com/submission-guidelines",
                "alternates": ("https://link.springer.com/journal/13059/submission-guidelines",),
                "provides": ("submission_steps", "license_of_summary_source"),
            },
            {
                "url": "https://link.springer.com/journal/13059/submission-guidelines/research",
                "provides": ("length_limits", "required_structure", "reference_style", "reporting_checklists", "figure_spec", "template"),
            },
        ),
        "evidence": {
            "length_limits": ("should not exceed 250 words",),
            "required_structure": ("declarations", "availability of data and materials", "conclusions"),
            "reference_style": ("vancouver",),
            "reporting_checklists": ("minimum standards of reporting",),
        },
        "unverified": ("figure_spec", "template", "license_of_summary_source"),
        "caveats": (
            "The note could not reach this venue at all: biomedcentral.com 301'd to link.springer.com, which 303'd to a "
            "Springer login endpoint, so the note marked every field unverified and left an action item to retry by another "
            "path. The retry is what this build does, and it pays: BMC's journals have moved onto Springer Nature Link and "
            "the research-article page now answers a stateless request, so the length, structure, reference and checklist "
            "fields below were read off a fetched page rather than a snippet.",
            "The figure specification and the template are still not stated on the pages reached.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": None,
                "page_count": None,
                "abstract_word_count": 250,
                "notes": "No length limit is stated for the main text. The abstract is capped at 250 words and is split into Background, Results and Conclusions. Three to ten keywords.",
                "excluded_sections": ["References", "Declarations"],
            },
            "required_structure": [
                "Title page", "Abstract", "Keywords", "Background", "Results", "Discussion",
                "Conclusions", "Methods", "Abbreviations", "Declarations",
                "Ethics approval and consent to participate", "Consent for publication",
                "Availability of data and materials", "Competing interests", "Funding",
                "Authors' contributions", "Acknowledgements", "References",
            ],
            "structure_flexible": False,
            "figure_spec": {
                "max_count": None,
                "formats": [],
                "min_dpi": None,
                "max_dpi": None,
                "color_mode": [],
                "max_file_size_mb": None,
                "legend_max_words": None,
                "notes": "Not stated on the pages reached.",
            },
            "reference_style": {
                "style": "Vancouver, numbered; footnotes rather than endnotes are asked for where notes are needed.",
                "max_count": None,
                "citation": "numbered",
            },
            "reporting_checklists": [
                {
                    "name": "BioMed Central Minimum Standards of Reporting Checklist",
                    "required": True,
                    "study_types": [],
                    "url": None,
                    "cache_as": None,
                },
            ],
            "submission_steps": [
                "submit through the journal's own online system; only an author of the manuscript may submit",
                "confirm at submission that the minimum reporting standards are met, or say why not",
                "include a Declarations section carrying every subheading, writing 'Not applicable' where one does not apply",
            ],
            "template": {
                "latex_or_word_no_login": None,
                "url": None,
                "notes": "Not stated on the pages reached.",
                "document_class": None,
            },
            "license_of_summary_source": {
                "statement": "Springer Nature Link's own terms cover the page; the journal publishes open access.",
                "url": "https://link.springer.com/journal/13059/submission-guidelines",
            },
        },
    },
    {
        "venue": "neurips",
        "display_name": "NeurIPS 2026",
        "sources": (
            {
                "url": "https://neurips.cc/Conferences/2026/CallForPapers",
                "provides": ("length_limits", "required_structure", "figure_spec", "reference_style", "submission_steps", "template", "license_of_summary_source"),
            },
            {
                "url": "https://neurips.cc/public/guides/PaperChecklist",
                "provides": ("reporting_checklists",),
            },
        ),
        "evidence": {
            "submission_steps": ("openreview", "may 6, 2026"),
            "reporting_checklists": ("paper checklist", "broader impacts"),
        },
        "unverified": ("length_limits", "figure_spec", "reference_style", "required_structure", "template.document_class"),
        "caveats": (
            "The call for papers defers the page limit to a Main Track Handbook the note did not fetch; the nine-page figure "
            "comes from the style file's formatting instructions as quoted in search results, so `length_limits` is unverified.",
            "The document class is the conference's usual naming rather than something either page states.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": None,
                "page_count": 9,
                "abstract_word_count": None,
                "notes": "Nine pages of main text including figures; acknowledgements, references, the paper checklist and optional appendices do not count. The figure is from the style file rather than from the call for papers.",
                "excluded_sections": ["Acknowledgements", "Acknowledgments", "References", "Checklist", "Appendix"],
            },
            "required_structure": ["NeurIPS Paper Checklist"],
            "structure_flexible": True,
            "figure_spec": {
                "max_count": None,
                "formats": [],
                "min_dpi": None,
                "max_dpi": None,
                "color_mode": [],
                "max_file_size_mb": None,
                "legend_max_words": None,
                "notes": "Not stated on either page fetched.",
            },
            "reference_style": {
                "style": "Set by the style file; neither page states one.",
                "max_count": None,
                "citation": "unknown",
            },
            "reporting_checklists": [
                {
                    "name": "NeurIPS Paper Checklist",
                    "required": True,
                    "study_types": [],
                    "url": "https://neurips.cc/public/guides/PaperChecklist",
                    "cache_as": None,
                },
            ],
            "submission_steps": [
                "submit through OpenReview at https://openreview.net/group?id=NeurIPS.cc/2026/Conference",
                "abstracts were due 4 May 2026 and full papers 6 May 2026, anywhere on Earth; notification 24 September 2026",
                "every author needs an OpenReview profile at abstract submission",
                "the paper checklist is mandatory and omitting it is grounds for desk rejection",
                "tracks do not accept switches and a paper may not be submitted to more than one",
            ],
            "template": {
                "latex_or_word_no_login": True,
                "url": "https://media.neurips.cc/Conferences/NeurIPS2026/Formatting_Instructions_For_NeurIPS_2026.zip",
                "notes": "A style-file zip downloads without a login and carries the checklist. Linked, never stored.",
                "document_class": "neurips_2026",
            },
            "license_of_summary_source": {
                "statement": "No copyright or licence notice appears on the page, only a cookie disclaimer.",
                "url": None,
            },
        },
    },
    {
        "venue": "icml",
        "display_name": "ICML 2026",
        "sources": (
            {
                "url": "https://icml.cc/Conferences/2026/CallForPapers",
                "provides": ("length_limits", "submission_steps", "license_of_summary_source"),
            },
            {
                "url": "https://icml.cc/Conferences/2026/AuthorInstructions",
                "provides": ("required_structure", "figure_spec", "reference_style", "reporting_checklists", "template"),
            },
        ),
        "evidence": {
            "length_limits": ("8 pages",),
            "required_structure": ("impact statement",),
            "submission_steps": ("openreview",),
        },
        "unverified": ("figure_spec.color_mode", "reference_style", "template.document_class"),
        "caveats": (
            "The eight-page submission limit is on the call for papers and the nine-page camera-ready limit on the author "
            "instructions, so the build fetches both.",
            "ICML ships a style package rather than a document class: a draft loads it with \\usepackage, which is what the "
            "conformance check looks for.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": None,
                "page_count": 8,
                "abstract_word_count": None,
                "notes": "Eight pages of main paper at submission and nine at camera-ready; references, the impact statement and appendices are unlimited. The submission PDF is capped at 50 MB and the camera-ready at 20 MB.",
                "excluded_sections": ["References", "Impact Statement", "Acknowledgements", "Acknowledgments", "Appendix"],
            },
            "required_structure": ["Impact Statement"],
            "structure_flexible": True,
            "figure_spec": {
                "max_count": None,
                "formats": ["EPS", "PDF"],
                "min_dpi": None,
                "max_dpi": None,
                "color_mode": [],
                "max_file_size_mb": 50,
                "legend_max_words": None,
                "notes": "Vector graphics are preferred for plots; bitmaps are permitted only for illustrations that cannot be vectorised. The size cap is the whole submission PDF, not one figure.",
            },
            "reference_style": {
                "style": "Not stated; the guidance is about content, replacing arXiv citations with peer-reviewed versions and fixing bibliographic capitalisation.",
                "max_count": None,
                "citation": "unknown",
            },
            "reporting_checklists": [],
            "submission_steps": [
                "submit through OpenReview at https://openreview.net/group?id=ICML.cc/2026/Conference",
                "abstracts were due 23 January 2026 and full papers 28 January 2026, anywhere on Earth",
                "anonymise for double-blind review",
                "add a lay summary and a conflict-of-interest paragraph at camera-ready",
                "accepted papers publish through PMLR under its publication agreement",
            ],
            "template": {
                "latex_or_word_no_login": True,
                "url": "https://media.icml.cc/Conferences/ICML2026/Styles/icml2026.zip",
                "notes": "A style-file zip downloads without a login. Linked, never stored.",
                "document_class": "icml2026",
            },
            "license_of_summary_source": {
                "statement": "No copyright or licence statement appears on the page; it links a privacy policy and a code of conduct.",
                "url": None,
            },
        },
    },
    {
        "venue": "iclr",
        "display_name": "ICLR 2027",
        "sources": (
            {
                "url": "https://iclr.cc/Conferences/2027/AuthorGuidelines",
                "provides": VERIFIED_FIELDS,
            },
        ),
        "evidence": {
            "length_limits": ("9 pages", "10 pages"),
            "required_structure": ("reproducibility statement", "ethics statement"),
            "submission_steps": ("openreview",),
        },
        "unverified": ("figure_spec", "reference_style", "template.document_class", "license_of_summary_source"),
        "caveats": (
            "The page states no figure specification, no citation style and no licence for its own text.",
            "ICLR ships a style package rather than a document class, loaded with \\usepackage; the name here follows the "
            "conference's usual spelling rather than the page.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": None,
                "page_count": 9,
                "abstract_word_count": None,
                "notes": "Nine pages of main text at submission, rising to ten for the discussion phase and camera-ready. References are unlimited and do not count. Appendices follow the bibliography and may be any length, though reviewers need not read them.",
                "excluded_sections": ["References", "Ethics Statement", "Reproducibility Statement", "Appendix", "Acknowledgements", "Acknowledgments"],
            },
            "required_structure": ["AI-use statement"],
            "structure_flexible": True,
            "figure_spec": {
                "max_count": None,
                "formats": [],
                "min_dpi": None,
                "max_dpi": None,
                "color_mode": [],
                "max_file_size_mb": None,
                "legend_max_words": None,
                "notes": "Not stated on the page.",
            },
            "reference_style": {
                "style": "Not stated on the page; the style file sets it. Self-citations are written in the third person.",
                "max_count": None,
                "citation": "unknown",
            },
            "reporting_checklists": [],
            "submission_steps": [
                "submit through OpenReview at https://openreview.net/group?id=ICLR.cc/2027/Conference",
                "submit the paper and any supplementary material as a single file",
                "include the mandatory AI-use statement, which does not count toward the page limit",
                "an ethics statement of up to one page and a reproducibility statement are optional and uncounted",
                "the cycle caps an author at 20 papers and ties reviewing quotas to submissions",
            ],
            "template": {
                "latex_or_word_no_login": True,
                "url": "https://media.iclr.cc/Conferences/ICLR2027/iclr-2027-style-files.zip",
                "notes": "A style-file zip downloads without a login; no Word template is mentioned. Linked, never stored.",
                "document_class": "iclr2027_conference",
            },
            "license_of_summary_source": {
                "statement": "No copyright or terms-of-use statement was found on the page.",
                "url": None,
            },
        },
    },
    {
        "venue": "biorxiv",
        "display_name": "bioRxiv",
        "sources": (
            {
                "url": "https://www.biorxiv.org/submit-a-manuscript",
                "provides": VERIFIED_FIELDS,
            },
        ),
        "evidence": {
            "figure_spec": ("jpeg, tiff, eps, powerpoint", "pict"),
            "submission_steps": ("single pdf",),
        },
        "unverified": ("length_limits", "reference_style", "license_of_summary_source"),
        "caveats": (
            "The page addresses metadata and file formats rather than a section list or a length limit, so those fields "
            "record an absence rather than a rule.",
            "A separate screening-procedures page exists and was not fetched.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": None,
                "page_count": None,
                "abstract_word_count": None,
                "notes": "No length limit is stated on the submission page.",
                "excluded_sections": [],
            },
            "required_structure": ["Title", "Abstract", "Authors", "Affiliations"],
            "structure_flexible": True,
            "figure_spec": {
                "max_count": None,
                "formats": ["JPEG", "TIFF", "EPS", "PPT"],
                "min_dpi": None,
                "max_dpi": None,
                "color_mode": [],
                "max_file_size_mb": None,
                "legend_max_words": None,
                "notes": "PICT, BMP, Excel and PSD files are not accepted and must be converted to PDF or an accepted format first.",
            },
            "reference_style": {
                "style": "Not addressed on the submission page.",
                "max_count": None,
                "citation": "any",
            },
            "reporting_checklists": [],
            "submission_steps": [
                "register on the site and supply an institutional affiliation",
                "upload one PDF of text and figures, or a Word file plus separate figure files, at submit.biorxiv.org",
                "supply the full author list with affiliations, corresponding-author contact details, funding sources and a competing-interests declaration",
                "expect basic screening for non-scientific content and health or biosecurity risk",
            ],
            "template": {
                "latex_or_word_no_login": False,
                "url": None,
                "notes": "No Word or LaTeX template is mentioned on the page.",
                "document_class": None,
            },
            "license_of_summary_source": {
                "statement": "Authors choose a posting licence from CC BY, CC BY-NC, CC BY-ND, CC BY-NC-ND, CC0 or no reuse, and keep copyright in every case; the page states no licence for its own text.",
                "url": "https://www.biorxiv.org/submit-a-manuscript",
            },
        },
    },
    {
        "venue": "arxiv",
        "display_name": "arXiv",
        "sources": (
            {
                "url": "https://info.arxiv.org/help/submit/index.html",
                "provides": ("length_limits", "required_structure", "figure_spec", "reference_style", "reporting_checklists", "submission_steps", "template"),
            },
            {
                "url": "https://info.arxiv.org/help/license/index.html",
                "provides": ("license_of_summary_source",),
            },
        ),
        "evidence": {
            "figure_spec": ("postscript", "pdflatex"),
            "required_structure": ("documentclass",),
            "submission_steps": ("14:00", "endorsement"),
        },
        "unverified": ("reference_style", "template"),
        "caveats": (
            "arXiv states no length limit, no section list and no citation style; the fields record that rather than a rule.",
            "Whether a template exists elsewhere on the help site was not checked.",
        ),
        "guidelines": {
            "length_limits": {
                "word_count": None,
                "page_count": None,
                "abstract_word_count": None,
                "notes": "No length limit: submissions must be topical, refereeable scientific contributions following accepted standards of scholarly communication.",
                "excluded_sections": [],
            },
            "required_structure": ["Title", "Abstract"],
            "structure_flexible": True,
            "figure_spec": {
                "max_count": None,
                "formats": ["PS", "EPS", "JPEG", "GIF", "PNG", "PDF"],
                "min_dpi": None,
                "max_dpi": None,
                "color_mode": [],
                "max_file_size_mb": None,
                "legend_max_words": None,
                "notes": "PostScript and EPS need LaTeX processing; JPEG, GIF, PNG and PDF need pdfLaTeX. Formats may not be mixed within one submission, and figures must be embedded rather than linked.",
            },
            "reference_style": {
                "style": "None: arXiv has no house citation style and leaves it to the author or the target journal.",
                "max_count": None,
                "citation": "any",
            },
            "reporting_checklists": [],
            "submission_steps": [
                "upload the files individually or as a zip or tar.gz through arXiv's own submission system",
                "select the compiler and the top-level TeX file, which must carry a \\documentclass directive",
                "review the auto-detected file issues and preview the compiled PDF",
                "fill the metadata page, then submit",
                "submissions received by 14:00 US Eastern are generally public around 20:00 the same day",
                "every submission is moderated for topicality; a new user or a new category may need an endorsement",
            ],
            "template": {
                "latex_or_word_no_login": None,
                "url": None,
                "notes": "No template is linked from the submission help page.",
                "document_class": None,
            },
            "license_of_summary_source": {
                "statement": "Authors choose CC BY 4.0, CC BY-SA 4.0, CC BY-NC-SA 4.0, CC BY-NC-ND 4.0, arXiv's own perpetual non-exclusive licence 1.0, or CC0, and grant arXiv an irrevocable distribution licence either way; article metadata is separately CC0 1.0.",
                "url": "https://info.arxiv.org/help/license/index.html",
            },
        },
    },
)


# --- reading a fetched page ----------------------------------------------------------------------

_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_MARKUP = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")

# The build asks for gzip: seventeen publisher pages recorded raw would outweigh every other
# fixture in the suite put together, and the bandwidth saved is the publisher's.
PAGE_HEADERS = {"Accept-Encoding": "gzip"}


def page_text(response):
    """A fetched page as the flat, entity-free, whitespace-collapsed text the evidence is matched in.

    Not a parser: scripts and styles go, tags go, entities are resolved, and runs of whitespace
    (a non-breaking space included, which is what publishers put between a number and its unit)
    become one space. That is enough to find a sentence the note read, and it is all this needs.
    """
    body = response.body
    if str(response.headers.get("content-encoding", "")).lower() == "gzip":
        try:
            body = gzip.decompress(body)
        except (OSError, EOFError, gzip.BadGzipFile):
            pass
    text = html.unescape(_MARKUP.sub(" ", _SCRIPT.sub(" ", body.decode("utf-8", errors="replace"))))
    return _SPACES.sub(" ", text.replace("\xa0", " ")).strip()


# --- the build ----------------------------------------------------------------------------------


def venue_seed(slug):
    """The recorded entry for one venue, by its directory name."""
    for seed in VENUES:
        if seed["venue"] == slug:
            return seed
    raise GuidelinesError("no venue %r; %s records %s" % (slug, NOTE, ", ".join(seed["venue"] for seed in VENUES)))


def _fetch(fetcher, url):
    """One page: `(status, text, note)`, where a status of None is a request that made no response."""
    try:
        answer = fetcher.fetch(url, headers=dict(PAGE_HEADERS))
    except FetchError as failure:
        return None, "", str(failure)
    if not answer.ok:
        return answer.status, "", None
    return answer.status, page_text(answer), None


def _reach(fetcher, source):
    """A source's URL, then its alternates in order; every try recorded, the first hit kept."""
    attempts, text = [], ""
    for url in (source["url"],) + tuple(source.get("alternates") or ()):
        status, body, note = _fetch(fetcher, url)
        outcome = "hit" if body else ("error" if status is None else "miss")
        attempts.append({"url": url, "status": status, "outcome": outcome, "note": note})
        if body:
            text = body
            break
    return attempts, text


def _unverified_paths(seed, field):
    """The sub-paths of `field` the research note itself could not confirm."""
    return tuple(
        path for path in seed.get("unverified", ())
        if path == field or path.startswith(field + ".")
    )


def _note_reason(seed, field, default):
    """Why the note left a field unconfirmed, in the venue's own terms where the seed gives one."""
    return seed.get("unverified_reasons", {}).get(field, default)


def _verify(seed, reached_text, unreachable):
    """Which fields survive the build, and why the rest do not.

    Three reasons a field can fail, in the order they are checked, because the first that applies
    is the one worth telling a reader: the note never confirmed it, the page it came from was not
    reached, or the page no longer carries the wording the note read.
    """
    verified, unverified, reasons = [], [], {}
    for field in VERIFIED_FIELDS:
        by_note = _unverified_paths(seed, field)
        missing_sources = sorted(unreachable.get(field, ()))
        gone = [marker for marker in seed["evidence"].get(field, ()) if marker.lower() not in reached_text]
        if field in by_note:
            unverified.append(field)
            reasons[field] = _note_reason(seed, field, "%s could not confirm it" % NOTE)
        elif missing_sources:
            unverified.append(field)
            reasons[field] = "not reached at build time: %s" % ", ".join(missing_sources)
        elif gone:
            unverified.append(field)
            reasons[field] = "the page no longer carries %s" % ", ".join(repr(marker) for marker in gone)
        elif by_note:
            # The page answered and its wording held, but the note was partial: the parts it could
            # not confirm are named, and a field confirmed only in part is not fully verified.
            unverified.extend(by_note)
            reasons[field] = _note_reason(seed, field, "%s confirmed the rest of the field but not this" % NOTE)
        else:
            verified.append(field)
    return verified, unverified, reasons


def _checklists(seed, fetcher, directory, cache):
    """Cache the reporting-checklist forms a venue publishes without a login. Templates never."""
    cached, entries = [], []
    for form in seed["guidelines"]["reporting_checklists"]:
        entry = {key: form[key] for key in ("name", "required", "study_types", "url")}
        entry["cached_as"] = None
        name = form.get("cache_as")
        if cache and name and form.get("url"):
            try:
                answer = fetcher.fetch(form["url"], headers=dict(PAGE_HEADERS))
            except FetchError as failure:
                cached.append({"name": form["name"], "file": name, "status": None, "note": str(failure)})
                entries.append(entry)
                continue
            if answer.ok and answer.body:
                path = directory / CHECKLIST_DIR / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(answer.body)
                entry["cached_as"] = "%s/%s" % (CHECKLIST_DIR, name)
                cached.append({"name": form["name"], "file": name, "status": answer.status, "note": None})
            else:
                cached.append({"name": form["name"], "file": name, "status": answer.status, "note": "not cached"})
        entries.append(entry)
    return entries, cached


def build_venue(seed, fetcher, root=None, today=None, cache_checklists=True):
    """Fetch one venue's pages, write its three files, and report what could still be believed."""
    root = Path(root if root is not None else HARNESS_ROOT)
    directory = root / GUIDELINES_DIR / seed["venue"]
    directory.mkdir(parents=True, exist_ok=True)

    attempts, texts, unreachable = [], [], {}
    primary_reached = False
    for index, source in enumerate(seed["sources"]):
        tried, text = _reach(fetcher, source)
        attempts.extend(tried)
        if text:
            texts.append(text)
            if index == 0:
                primary_reached = True
        else:
            for field in source["provides"]:
                unreachable.setdefault(field, set()).add(source["url"])
    reached_text = " ".join(texts).lower()

    verified, unverified, reasons = _verify(seed, reached_text, unreachable)
    checklists, cached = _checklists(seed, fetcher, directory, cache_checklists)

    guidelines = {
        "schema_version": 1,
        "venue": seed["venue"],
        "display_name": seed["display_name"],
        "guidelines_url": seed["sources"][0]["url"],
        "date_checked": (today or date.today().isoformat()) if primary_reached else NOTE_DATE,
    }
    # In the spec's order, so a reader of one venue's file finds the same field in the same place
    # in every other. The checklists are the build's rather than the seed's: they are the only
    # field that carries what the build did (what it cached) as well as what the note recorded.
    for field in ("length_limits", "required_structure", "structure_flexible", "figure_spec",
                  "reference_style", "reporting_checklists", "submission_steps", "template",
                  "license_of_summary_source"):
        guidelines[field] = checklists if field == "reporting_checklists" else deepcopy(seed["guidelines"][field])
    guidelines["verification"] = {"fully_verified_fields": verified, "unverified_fields": unverified}
    check(guidelines, load_schema("guidelines"), name="guidelines/%s/%s" % (seed["venue"], GUIDELINES_JSON))

    report = {
        "venue": seed["venue"],
        "display_name": seed["display_name"],
        "date_checked": guidelines["date_checked"],
        "reached": primary_reached,
        "attempts": attempts,
        "fully_verified_fields": verified,
        "unverified_fields": unverified,
        "reasons": reasons,
        "checklists": cached,
    }
    (directory / GUIDELINES_JSON).write_text(
        json.dumps(guidelines, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (directory / SOURCE_MD).write_text(render_source(seed, report), encoding="utf-8")
    return report


def build(root=None, fetcher=None, venues=None, today=None, cache_checklists=True):
    """Build `guidelines/<venue>/` for every recorded venue, or for the ones named."""
    fetcher = fetcher if fetcher is not None else Fetcher()
    seeds = [venue_seed(slug) for slug in venues] if venues else list(VENUES)
    reports = [build_venue(seed, fetcher, root=root, today=today, cache_checklists=cache_checklists) for seed in seeds]
    return {
        "venues": reports,
        "built": len(reports),
        "reached": sum(1 for report in reports if report["reached"]),
        "unreachable": [report["venue"] for report in reports if not report["reached"]],
    }


def read_guidelines(root, venue=None):
    """One venue's `guidelines.json`, validated; this is what every check reads and all it reads.

    `root` is a harness directory and `venue` a slug under its `guidelines/`, or `root` is the
    path of a `guidelines.json` itself and `venue` is left out.
    """
    path = Path(root) if venue is None else Path(root) / GUIDELINES_DIR / venue / GUIDELINES_JSON
    try:
        guidelines = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise GuidelinesError("no guidelines at %s; run `wayline guidelines build`" % path) from None
    except ValueError as failure:
        raise GuidelinesError("%s is not readable JSON: %s" % (path, failure)) from None
    check(guidelines, load_schema("guidelines"), name=str(path))
    return guidelines


def render_source(seed, report):
    """`source.md`: what was fetched, what is unverified and why, and the note's own caveats."""
    lines = [
        "# %s" % seed["display_name"],
        "",
        "What this directory's `guidelines.json` was built from, and what in it cannot be believed "
        "without checking again. The fields were transcribed from `%s` (checked %s); the build "
        "re-fetches the pages below and looks for the wording the note read, so a field is fully "
        "verified only when its page answered and its wording is still there." % (NOTE, NOTE_DATE),
        "",
        "## Pages fetched",
        "",
        "| URL | Status | Outcome |",
        "|---|---|---|",
    ]
    for attempt in report["attempts"]:
        status = attempt["status"] if attempt["status"] is not None else "no response"
        lines.append("| %s | %s | %s |" % (attempt["url"], status, attempt["outcome"]))
    lines += ["", "`date_checked` is %s." % report["date_checked"]]
    if not report["reached"]:
        lines.append(
            "The page the venue's own `guidelines_url` names did not answer, so the date is the "
            "research note's rather than the build's."
        )
    lines += ["", "## Verification", ""]
    if report["fully_verified_fields"]:
        lines.append("Fully verified: %s." % ", ".join("`%s`" % field for field in report["fully_verified_fields"]))
    else:
        lines.append("Nothing in this file is fully verified.")
    lines.append("")
    if report["unverified_fields"]:
        lines.append("Unverified, and why:")
        lines.append("")
        for field in report["unverified_fields"]:
            head = field.split(".")[0]
            lines.append("- `%s`: %s." % (field, report["reasons"].get(head, report["reasons"].get(field, "not confirmed"))))
    else:
        lines.append("Nothing is unverified.")
    if report["checklists"]:
        lines += ["", "## Reporting-checklist forms", ""]
        for form in report["checklists"]:
            if form["note"] is None:
                lines.append("- %s cached as `%s/%s` (HTTP %s)." % (form["name"], CHECKLIST_DIR, form["file"], form["status"]))
            else:
                lines.append("- %s not cached: %s." % (form["name"], form["note"]))
    lines += [
        "",
        "## Caveats",
        "",
    ]
    lines += ["- %s" % caveat for caveat in seed["caveats"]] or ["- None recorded."]
    lines += [
        "",
        "Manuscript templates are linked from `guidelines.json` and never stored here; `checklist/` "
        "holds reporting-checklist forms only.",
        "",
    ]
    return "\n".join(lines)


# --- the manuscript the checks read ---------------------------------------------------------------

TEXT_SUFFIXES = (".md", ".markdown", ".tex")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".eps", ".ps", ".pdf", ".svg", ".gif")
VECTOR_SUFFIXES = (".eps", ".ps", ".pdf", ".svg")

_MD_HEADING = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*#*\s*$")
_TEX_HEADING = re.compile(r"\\(?:sub){0,2}section\*?\s*\{([^}]*)\}")
_TEX_ABSTRACT = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.DOTALL)
_TEX_COMMENT = re.compile(r"(?<!\\)%.*")
_TEX_DROP = re.compile(r"\\(?:label|ref|eqref|cite[a-z]*|includegraphics|usepackage|documentclass|bibliography(?:style)?|input|include)\s*(?:\[[^\]]*\])?\s*\{[^}]*\}")
_TEX_COMMAND = re.compile(r"\\[a-zA-Z@]+\*?\s*(?:\[[^\]]*\])?")
_TEX_MATH = re.compile(r"\$\$.*?\$\$|\$[^$]*\$", re.DOTALL)
_TEX_FIGURE = re.compile(r"\\begin\{(figure|table)\*?\}(.*?)\\end\{\1\*?\}", re.DOTALL)
_TEX_GRAPHIC = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_TEX_CAPTION = re.compile(r"\\caption\s*(?:\[[^\]]*\])?\s*\{(.*?)\}\s*(?:\\label|\n\s*\n|$)", re.DOTALL)
_TEX_CLASS = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_TEX_PACKAGE = re.compile(r"\\usepackage\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_TEX_BIBITEM = re.compile(r"\\bibitem\b")
_BIB_ENTRY = re.compile(r"(?m)^\s*@[A-Za-z]+\s*[{(]")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
_MD_FENCE = re.compile(r"(?ms)^```.*?^```\s*$")
_MD_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_MD_TABLE_ROW = re.compile(r"(?m)^\s*\|.*\|\s*$")
_LEGEND = re.compile(r"^\**\s*(?:figure|fig\.?|table)\s*\d+\s*[.:|]", re.IGNORECASE)
_NUMERIC_CITATION = re.compile(r"\[\d+(?:\s*[,-]\s*\d+)*\]|\[@[^\]]+\]")
_AUTHOR_DATE_CITATION = re.compile(r"\([A-Z][A-Za-z'’-]+(?:\s+(?:et al\.?|and|&)\s+[A-Z][A-Za-z'’-]+)?[,.]?\s*(?:19|20)\d{2}[a-z]?\)")
_WORD = re.compile(r"[A-Za-z0-9][\w'’\u2011-]*")
_PARAGRAPH = re.compile(r"\n\s*\n")


def _words(text):
    """Words a reader reads. A provenance tag is markup, not six words, so it comes off first.

    Every count in this module goes through here, which is why the tags are stripped here rather
    than in `Manuscript.prose`: the sentence pass reads the same prose and needs the tags kept.
    """
    return len(_WORD.findall(strip_tags(text)))


def _normalize(name):
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


class Manuscript:
    """A drafted manuscript on disk, read once: sections, figures, references, sentences.

    The checks are mechanical and so is this: nothing is parsed that a check does not ask about,
    Markdown and LaTeX are both read because Implementation Decisions 13 says a draft may be
    either, and a file that is neither is carried along only so the checklist check can see that
    it is there.
    """

    def __init__(self, path):
        # Resolved, because a figure a draft points at is resolved too, and the two are compared:
        # a relative `research/paper` and an absolute one have to describe the same package.
        self.root = Path(path).resolve()
        if self.root.is_file():
            # One file is one draft and no package. Its directory is not walked: a `paper.md` at a
            # project root would otherwise drag every `.bib` and every PDF in the repository into
            # the reference count and the page count.
            self.files, self.root = [self.root], self.root.parent
            self.all_files = list(self.files)
        elif self.root.is_dir():
            # `checklist/` holds the forms a submission carries, not the draft: a completed ARRIVE
            # form is part of the package the checklist check looks through and no part of the
            # word count, the section list or the sentences.
            self.all_files = sorted(self._walk())
            self.files = [
                found for found in self.all_files
                if found.suffix.lower() in TEXT_SUFFIXES
                and CHECKLIST_DIR not in found.relative_to(self.root).parts
            ]
        else:
            raise GuidelinesError("no manuscript at %s" % path)
        if not self.files:
            raise GuidelinesError("%s holds no .md or .tex file" % path)
        self.sources = {path: path.read_text(encoding="utf-8", errors="replace") for path in self.files}
        self.kind = "latex" if any(path.suffix.lower() == ".tex" for path in self.files) else "markdown"
        self._prose = None
        self._figures = None

    def _walk(self):
        """Every file under the draft's directory, skipping what a dot-directory holds.

        The dot test is on the path below the draft, not the whole of it: a project can sit
        anywhere, including under a `.claude/worktrees/` of its own, and a draft there is still a
        draft.
        """
        for found in self.root.rglob("*"):
            if found.is_file() and not any(part.startswith(".") for part in found.relative_to(self.root).parts):
                yield found

    # --- prose ---

    def prose(self, text=None):
        """Markup stripped down to the words a person reads, for counting and for sentences.

        The whole draft's prose is asked for by several checks at once, so it is stripped once and
        kept; a caller that passes its own text (one section, one legend) is not worth caching.
        """
        if text is None:
            if self._prose is None:
                self._prose = "\n\n".join(self.prose(body) for body in self.sources.values())
            return self._prose
        if self.kind == "latex":
            body = _TEX_COMMENT.sub("", text)
            body = body.split(r"\begin{document}", 1)[-1]
            body = _TEX_MATH.sub(" ", body)
            body = _TEX_DROP.sub(" ", body)
            body = _TEX_COMMAND.sub(" ", body)
            return body.replace("{", " ").replace("}", " ").replace("&", " ").replace("\\", " ")
        body = _MD_FENCE.sub(" ", text)
        body = _MD_HTML_COMMENT.sub(" ", body)
        body = _MD_IMAGE.sub(" ", body)
        body = _MD_LINK.sub(r"\1", body)
        body = re.sub(r"(?m)^#{1,6}\s+", "", body)
        return body.replace("*", "").replace("`", "")

    def sections(self):
        """`[(name, body)]` across every file, in file order; the text before the first heading is ''."""
        found = []
        for path, text in self.sources.items():
            if self.kind == "latex":
                abstract = _TEX_ABSTRACT.search(text)
                if abstract:
                    found.append(("Abstract", abstract.group(1)))
                    text = text[:abstract.start()] + text[abstract.end():]
                marks = list(_TEX_HEADING.finditer(text))
            else:
                marks = list(_MD_HEADING.finditer(text))
            if not marks:
                found.append(("", text))
                continue
            if marks[0].start() > 0:
                found.append(("", text[:marks[0].start()]))
            for index, mark in enumerate(marks):
                end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
                name = mark.group(2 if self.kind != "latex" else 1).strip()
                found.append((name, text[mark.end():end]))
        return found

    def section_names(self):
        return [name for name, _ in self.sections() if name]

    def title(self):
        """The draft's title: a LaTeX `\\title{}`, or the first level-one heading of a Markdown draft.

        A venue asking for a Title is asking for the title itself, not for a section called one,
        so this is what the section check reads instead of looking for the word.
        """
        for text in self.sources.values():
            if self.kind == "latex":
                found = re.search(r"\\title\s*(?:\[[^\]]*\])?\s*\{(.+?)\}", text, re.DOTALL)
                if found:
                    return self.prose(found.group(1)).strip()
            else:
                found = re.search(r"(?m)^#\s+(.+?)\s*#*\s*$", text)
                if found:
                    return found.group(1).strip()
        return None

    def body_words(self, excluded=()):
        """Words of main text: every named section but the abstract, the references, the venue's
        exclusions, and the figure legends inside what is left."""
        skip = {_normalize(name) for name in tuple(excluded) + ("abstract", "references", "bibliography")}
        total = 0
        for name, body in self.sections():
            if not name or _normalize(name) in skip:
                continue
            prose = self.prose(body)
            total += _words(prose) - sum(_words(legend) for legend in self._legend_paragraphs(prose))
        return total

    def abstract_words(self):
        for name, body in self.sections():
            if _normalize(name) == "abstract":
                return _words(self.prose(body))
        return None

    def _legend_paragraphs(self, prose):
        return [chunk for chunk in _PARAGRAPH.split(prose) if _LEGEND.match(chunk.strip())]

    # --- display items ---

    def figures(self):
        """Every figure: the file it points at (when it names one) and its legend.

        Figures only. A LaTeX `table` environment is a display item too, and `tables` counts it,
        but it is no figure: it points at no file and has no format, resolution or colour mode for
        the figure check to read.
        """
        if self._figures is not None:
            return self._figures
        found = []
        for path, text in self.sources.items():
            if self.kind == "latex":
                for kind, block in _TEX_FIGURE.findall(text):
                    if kind != "figure":
                        continue
                    caption = _TEX_CAPTION.search(block)
                    legend = self.prose(caption.group(1)) if caption else ""
                    for target in _TEX_GRAPHIC.findall(block) or [None]:
                        found.append({"kind": kind, "file": self._resolve(path, target), "legend": legend.strip()})
            else:
                paragraphs = _PARAGRAPH.split(text)
                for index, chunk in enumerate(paragraphs):
                    for alt, target in _MD_IMAGE.findall(chunk):
                        following = paragraphs[index + 1].strip() if index + 1 < len(paragraphs) else ""
                        legend = following if _LEGEND.match(following) else alt
                        found.append({"kind": "figure", "file": self._resolve(path, target), "legend": self.prose(legend).strip()})
        self._figures = found
        return found

    def tables(self):
        """Tables as display items: a `table` environment in LaTeX, a pipe table in Markdown."""
        blocks = 0
        for text in self.sources.values():
            if self.kind == "latex":
                blocks += sum(1 for kind, _ in _TEX_FIGURE.findall(text) if kind == "table")
            else:
                blocks += sum(1 for chunk in _PARAGRAPH.split(text) if len(_MD_TABLE_ROW.findall(chunk)) >= 2)
        return blocks

    def _resolve(self, source, target):
        if not target:
            return None
        candidate = (source.parent / target).resolve()
        if candidate.exists():
            return candidate
        for suffix in IMAGE_SUFFIXES:  # LaTeX omits the extension and lets the compiler find it
            guess = candidate.with_suffix(suffix)
            if guess.exists():
                return guess
        return candidate

    # --- references ---

    def references(self):
        """`(count, citation form)`; the count is 0 and the form 'unknown' when nothing says."""
        count = 0
        for path in self.all_files:
            if path.suffix.lower() == ".bib":
                count += len(_BIB_ENTRY.findall(path.read_text(encoding="utf-8", errors="replace")))
        if not count:
            for text in self.sources.values():
                count += len(_TEX_BIBITEM.findall(text))
        if not count:
            for name, body in self.sections():
                if _normalize(name) in ("references", "bibliography"):
                    count += len([1 for line in body.splitlines() if re.match(r"\s*(?:\[\d+\]|\d+\.|[-*])\s+\S", line)])
        return count, self.citation_form()

    def citation_form(self):
        source = "\n".join(self.sources.values())
        if self.kind == "latex":
            if re.search(r"\\cite[pt]\b|\\citealp\b|\\citeauthor\b", source):
                return "author-date"
            if re.search(r"\\cite\b|\\autocite\b", source):
                return "numbered"
        numeric = len(_NUMERIC_CITATION.findall(self.prose()))
        author_date = len(_AUTHOR_DATE_CITATION.findall(self.prose()))
        if numeric > author_date:
            return "numbered"
        if author_date > numeric:
            return "author-date"
        return "unknown"

    # --- the LaTeX preamble ---

    def document_classes(self):
        """Every class and package the draft loads; a conference style is a package, not a class."""
        source = "\n".join(self.sources.values())
        found = []
        for pattern in (_TEX_CLASS, _TEX_PACKAGE):
            for group in pattern.findall(source):
                found.extend(part.strip() for part in group.split(",") if part.strip())
        return found

    def pdf_pages(self):
        """The page count of a compiled PDF sitting beside the source, or None when there is none.

        The root of the page tree is the object that is a `/Pages` with no `/Parent`, and its
        `/Count` is the page count. Any `/Count` would be the wrong thing to read: a PDF built with
        hyperref carries an outline tree whose `/Count` is the number of bookmarks, which is
        usually larger than the number of pages and would fail a nine-page paper for being
        seventeen. Where no such object is found, the `/Type /Page` objects are counted instead.
        """
        for path in self.all_files:
            if path.suffix.lower() != ".pdf" or self._is_figure(path):
                continue
            body = path.read_bytes()
            for block in re.findall(rb"\bobj\b(.*?)\bendobj\b", body, re.DOTALL):
                if not re.search(rb"/Type\s*/Pages\b", block) or re.search(rb"/Parent\b", block):
                    continue
                count = re.search(rb"/Count\s+(\d+)", block)
                if count:
                    return int(count.group(1))
            pages = len(re.findall(rb"/Type\s*/Page[^s]", body))
            if pages:
                return pages
        return None

    def _is_figure(self, path):
        return any(figure["file"] == path for figure in self.figures())

    # --- what the other two checks need ---

    def sentence_pass(self):
        """Every prose sentence of the draft with its provenance tags, as `provenance.sentences`."""
        return [sentence for path in self.files for sentence in sentences(self.prose(self.sources[path]))]

    def text(self):
        return self.prose()

    def study_types(self):
        """The study types the draft's own words claim, by the keyword heuristic of note 10."""
        lowered = self.prose().lower()
        return sorted(kind for kind, words in STUDY_TYPES.items() if any(word in lowered for word in words))

    def file_names(self):
        return [path.name for path in self.all_files]


# --- image metadata, without a third-party imaging library -----------------------------------------


# One spelling per format, because a venue writes TIF where a file is named .tiff and JPG where
# another venue writes JPEG. Both sides of the format check are folded through this, so a draft is
# never told its .tif is the wrong format at a venue whose own list says TIF.
_FORMAT_NAMES = {"TIF": "TIFF", "JPG": "JPEG", "PS": "PS", "EPS": "EPS", "PPT": "PPT", "PPTX": "PPT"}


def _format_name(suffix_or_name):
    name = str(suffix_or_name or "").strip().lstrip(".").upper()
    return _FORMAT_NAMES.get(name, name)


def image_facts(path):
    """Format, resolution, colour mode and size of one figure file, read from its own header.

    The harness imports no third-party package, so PNG, JPEG and TIFF headers are read here: a
    PNG's `pHYs` chunk and `IHDR` colour type, a JPEG's JFIF density and `SOF` component count, a
    TIFF's resolution and photometric tags. A vector file carries no resolution and says so rather
    than claiming one.
    """
    path = Path(path)
    facts = {
        "format": _format_name(path.suffix) or None,
        "dpi": None,
        "color_mode": None,
        "size_mb": None,
        "vector": path.suffix.lower() in VECTOR_SUFFIXES,
    }
    try:
        facts["size_mb"] = round(path.stat().st_size / 1_000_000, 3)
        head = path.read_bytes()
    except OSError:
        return facts
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        _png_facts(head, facts)
    elif head[:2] == b"\xff\xd8":
        _jpeg_facts(head, facts)
    elif head[:4] in (b"II*\x00", b"MM\x00*"):
        _tiff_facts(head, facts)
    return facts


_PNG_COLOR = {0: "grayscale", 2: "RGB", 3: "RGB", 4: "grayscale", 6: "RGB"}


def _png_facts(body, facts):
    at = 8
    while at + 8 <= len(body):
        length = int.from_bytes(body[at:at + 4], "big")
        kind = body[at + 4:at + 8]
        payload = body[at + 8:at + 8 + length]
        if kind == b"IHDR" and len(payload) >= 10:
            facts["color_mode"] = _PNG_COLOR.get(payload[9])
        elif kind == b"pHYs" and len(payload) >= 9 and payload[8] == 1:  # 1: pixels per metre
            facts["dpi"] = round(int.from_bytes(payload[0:4], "big") * 0.0254)
        elif kind == b"IDAT":
            break
        at += 12 + length


def _jpeg_facts(body, facts):
    at = 2
    while at + 4 <= len(body):
        if body[at] != 0xFF:
            at += 1
            continue
        marker, length = body[at + 1], int.from_bytes(body[at + 2:at + 4], "big")
        if length < 2:  # a segment that claims no length would walk this loop forever
            break
        payload = body[at + 4:at + 2 + length]
        if marker == 0xE0 and payload[:5] == b"JFIF\x00" and len(payload) >= 12:
            units, density = payload[7], int.from_bytes(payload[8:10], "big")
            if units == 1 and density:
                facts["dpi"] = density
            elif units == 2 and density:  # dots per centimetre
                facts["dpi"] = round(density * 2.54)
        elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC) and len(payload) >= 6:
            facts["color_mode"] = {1: "grayscale", 3: "RGB", 4: "CMYK"}.get(payload[5])
            break
        elif marker == 0xDA:
            break
        at += 2 + length


_TIFF_PHOTOMETRIC = {0: "grayscale", 1: "grayscale", 2: "RGB", 3: "RGB", 5: "CMYK"}


def _tiff_facts(body, facts):
    order = "little" if body[:2] == b"II" else "big"

    def number(at, size):
        return int.from_bytes(body[at:at + size], order)

    offset = number(4, 4)
    if offset + 2 > len(body):
        return
    resolution, unit = None, 2
    for index in range(number(offset, 2)):
        entry = offset + 2 + index * 12
        tag, kind, value_at = number(entry, 2), number(entry + 2, 2), entry + 8
        if tag == 262:
            facts["color_mode"] = _TIFF_PHOTOMETRIC.get(number(value_at, 2))
        elif tag == 282 and kind == 5:  # XResolution, a rational at an offset
            at = number(value_at, 4)
            denominator = number(at + 4, 4)
            resolution = number(at, 4) / denominator if denominator else None
        elif tag == 296:
            unit = number(value_at, 2)
    if resolution:
        facts["dpi"] = round(resolution if unit != 3 else resolution * 2.54)


# --- the seven checks -----------------------------------------------------------------------------

Finding = namedtuple("Finding", "check level message")

LEVEL_ORDER = {"ok": 0, "skipped": 0, "warn": 1, "fail": 2}


def check_length(manuscript, guidelines):
    """1. Word or page count, with the venue's own exclusions."""
    limits = guidelines["length_limits"]
    findings = []
    words = manuscript.body_words(limits["excluded_sections"])
    if limits["word_count"] is None:
        findings.append(Finding("length", "ok" if limits["page_count"] else "skipped",
                                 "%s sets no word limit; the main text is %d words." % (guidelines["display_name"], words)))
    elif words > limits["word_count"]:
        findings.append(Finding("length", "fail", "the main text is %d words, over the %d %s allows%s."
                                 % (words, limits["word_count"], guidelines["display_name"],
                                    " (excluding %s)" % ", ".join(limits["excluded_sections"]) if limits["excluded_sections"] else "")))
    else:
        findings.append(Finding("length", "ok", "the main text is %d words, within %d." % (words, limits["word_count"])))

    abstract = manuscript.abstract_words()
    if limits["abstract_word_count"] is not None and abstract is not None:
        level = "fail" if abstract > limits["abstract_word_count"] else "ok"
        findings.append(Finding("length", level, "the abstract is %d words against a limit of %d."
                                 % (abstract, limits["abstract_word_count"])))
    elif limits["abstract_word_count"] is not None:
        findings.append(Finding("length", "warn", "no Abstract section was found, and %s caps it at %d words."
                                 % (guidelines["display_name"], limits["abstract_word_count"])))

    if limits["page_count"] is not None:
        pages = manuscript.pdf_pages()
        if pages is None:
            findings.append(Finding("length", "skipped",
                                     "%s counts pages (%d), and nothing here compiles LaTeX; put the built PDF beside the "
                                     "source and the check reads its page count." % (guidelines["display_name"], limits["page_count"])))
        else:
            level = "fail" if pages > limits["page_count"] else "ok"
            findings.append(Finding("length", level, "the compiled PDF is %d pages against a limit of %d." % (pages, limits["page_count"])))
    return findings


# The section words that have two spellings, so a draft is not told it is missing a section it
# spells the other way. Nothing wider: this is a section-name fold, not a dictionary.
_SPELLINGS = {
    "acknowledgements": "acknowledgments",
    "summarise": "summarize",
    "behavioural": "behavioral",
    "randomised": "randomized",
}


def _fold(word):
    return _SPELLINGS.get(word, word)


def _heading_matches(required, heading):
    """Whether a heading is the section a venue asked for, comparing words rather than substrings.

    Word by word, because a substring test makes "Authors" present in a draft whose only such
    heading is "Author summary". One list being a run of the other is a match in both directions:
    a venue asking for "Materials and Methods" is satisfied by a draft that calls it "Methods",
    and a venue asking for "Methods" by a draft that spells it out.
    """
    wanted = [_fold(word) for word in re.findall(r"[a-z0-9]+", required.lower())]
    found = [_fold(word) for word in re.findall(r"[a-z0-9]+", heading.lower())]
    if not wanted or not found:
        return False
    short, long = (wanted, found) if len(wanted) <= len(found) else (found, wanted)
    return any(long[at:at + len(short)] == short for at in range(len(long) - len(short) + 1))


def check_structure(manuscript, guidelines):
    """2. Section presence, a warning rather than a failure where the venue is flexible."""
    required = guidelines["required_structure"]
    if not required:
        return [Finding("structure", "skipped", "%s names no required sections." % guidelines["display_name"])]
    headings = manuscript.section_names()
    title = manuscript.title()
    missing = [
        name for name in required
        if not any(_heading_matches(name, heading) for heading in headings)
        and not (title and _normalize(name) in ("title", "titlepage"))
    ]
    if not missing:
        return [Finding("structure", "ok", "every one of the %d section(s) %s asks for is present." % (len(required), guidelines["display_name"]))]
    level = "warn" if guidelines["structure_flexible"] else "fail"
    return [Finding("structure", level, "%s: %s%s" % (
        "missing section" if len(missing) == 1 else "missing sections",
        ", ".join(missing),
        "; %s is structure-flexible, so this is a warning" % guidelines["display_name"] if level == "warn" else "",
    ))]


def check_figures(manuscript, guidelines):
    """3. Figure count, format, resolution, colour mode, file size, and legend length."""
    spec = guidelines["figure_spec"]
    figures = manuscript.figures()
    findings = []

    if spec["max_count"] is not None:
        items = len(figures) + manuscript.tables()
        level = "fail" if items > spec["max_count"] else "ok"
        findings.append(Finding("figures", level, "%d display item(s) against a limit of %d." % (items, spec["max_count"])))
    else:
        findings.append(Finding("figures", "ok", "%d figure(s); %s caps none." % (len(figures), guidelines["display_name"])))

    accepted = {_format_name(name) for name in spec["formats"]}
    for figure in figures:
        path = figure["file"]
        if path is None or not Path(path).exists():
            findings.append(Finding("figures", "warn", "a figure points at %s, which is not on disk."
                                     % (figure["file"].name if figure["file"] else "no file")))
            continue
        facts = image_facts(path)
        name = Path(path).name
        if accepted and facts["format"] not in accepted:
            findings.append(Finding("figures", "fail", "%s is %s; %s accepts %s."
                                     % (name, facts["format"], guidelines["display_name"], ", ".join(sorted(accepted)))))
        if spec["min_dpi"] is not None and not facts["vector"]:
            if facts["dpi"] is None:
                findings.append(Finding("figures", "warn", "%s carries no resolution in its header, and %s asks for at least %d dpi."
                                         % (name, guidelines["display_name"], spec["min_dpi"])))
            elif facts["dpi"] < spec["min_dpi"]:
                findings.append(Finding("figures", "fail", "%s is %d dpi, under the %d %s asks for."
                                         % (name, facts["dpi"], spec["min_dpi"], guidelines["display_name"])))
        if spec["max_dpi"] is not None and facts["dpi"] is not None and facts["dpi"] > spec["max_dpi"]:
            findings.append(Finding("figures", "warn", "%s is %d dpi, over the %d %s asks for."
                                     % (name, facts["dpi"], spec["max_dpi"], guidelines["display_name"])))
        if spec["color_mode"] and facts["color_mode"] and facts["color_mode"] not in spec["color_mode"]:
            findings.append(Finding("figures", "fail", "%s is %s; %s takes %s."
                                     % (name, facts["color_mode"], guidelines["display_name"], ", ".join(spec["color_mode"]))))
        if spec["max_file_size_mb"] is not None and facts["size_mb"] is not None and facts["size_mb"] > spec["max_file_size_mb"]:
            findings.append(Finding("figures", "fail", "%s is %.1f MB, over the %s MB limit."
                                     % (name, facts["size_mb"], spec["max_file_size_mb"])))

    if spec["legend_max_words"] is not None:
        for index, figure in enumerate(figures, start=1):
            count = _words(figure["legend"])
            if count > spec["legend_max_words"]:
                findings.append(Finding("figures", "fail", "the legend of figure %d is %d words, over %d."
                                         % (index, count, spec["legend_max_words"])))
    return findings


def check_references(manuscript, guidelines):
    """4. Reference style and count."""
    style = guidelines["reference_style"]
    count, form = manuscript.references()
    findings = []
    if style["citation"] in ("numbered", "author-date"):
        if form == "unknown":
            findings.append(Finding("references", "warn", "no in-text citation was recognised; %s wants %s."
                                     % (guidelines["display_name"], style["citation"])))
        elif form != style["citation"]:
            findings.append(Finding("references", "fail", "the draft cites %s; %s wants %s."
                                     % (form, guidelines["display_name"], style["citation"])))
        else:
            findings.append(Finding("references", "ok", "%s citations, as %s wants." % (form, guidelines["display_name"])))
    else:
        findings.append(Finding("references", "skipped", "%s sets no citation form (%s)."
                                 % (guidelines["display_name"], style["style"])))
    if style["max_count"] is not None:
        level = "fail" if count > style["max_count"] else "ok"
        findings.append(Finding("references", level, "%d reference(s) against a limit of %d." % (count, style["max_count"])))
    elif count:
        findings.append(Finding("references", "ok", "%d reference(s); %s caps none." % (count, guidelines["display_name"])))
    return findings


# What a long-named form is called in practice. A key has to be distinctive enough that no
# ordinary file name carries it by accident, which is why these are phrases rather than words:
# matching a form's first word alone would let `reporting-notes.md` pass for a Reporting Summary,
# and a checklist the package does not have is the one thing this check must not say it has. The
# names on the left are `guidelines.json`'s, so a venue built from another seed needs no entry
# here unless its form is filed under something shorter than its title.
CHECKLIST_ALIASES = {
    "BioMed Central Minimum Standards of Reporting Checklist": (
        "minimum standards of reporting", "bmc checklist", "bmc minimum standards",
    ),
    "NeurIPS Paper Checklist": ("neurips checklist", "paper checklist"),
    "Reporting Summary": ("reporting summary",),
    "Key Resources Table": ("key resources",),
    "Inclusion in Global Research form": ("inclusion in global research",),
    "Editorial policy checklist": ("editorial policy",),
    "Code and software submission checklist": ("code and software",),
    "Cell Press reporting checklists": ("cell press checklist",),
    "Clinical trial checklist": ("clinical trial checklist",),
}


def _checklist_keys(name):
    """What a file or a section has to be called to count as this checklist.

    Three kinds of key: the whole name, the acronym where the form has one (ARRIVE, PRISMA, MDAR,
    STROBE-MR are filed under it), and the phrases `CHECKLIST_ALIASES` records for the forms whose
    full title nobody types. Without the third, Genome Biology's "BioMed Central Minimum Standards
    of Reporting Checklist" could be matched by no file a person would ever name, and every draft
    for that venue failed a check it could not pass.
    """
    keys = [_normalize(name)]
    words = name.split()
    head = _normalize(words[0]) if words else ""
    if words and words[0].isupper() and len(head) >= 4 and head not in keys:
        keys.append(head)
    for alias in CHECKLIST_ALIASES.get(name, ()):
        if _normalize(alias) not in keys:
            keys.append(_normalize(alias))
    return keys


def check_reporting_checklists(manuscript, guidelines):
    """5. Reporting-checklist presence, by the study type the draft's own words claim."""
    forms = guidelines["reporting_checklists"]
    if not forms:
        return [Finding("reporting_checklists", "skipped", "%s names no reporting checklist." % guidelines["display_name"])]
    kinds = set(manuscript.study_types())
    # A form is in the package when a file carries its name, and also when the draft itself does:
    # a conference checklist lives inside the manuscript as a section rather than beside it as a
    # form, and asking for a file that no submission has would be a check nobody can pass.
    places = [(_normalize(name), "the package") for name in manuscript.file_names()]
    places += [(_normalize(name), "the draft") for name in manuscript.section_names()]
    findings = []
    for form in forms:
        wanted = not form["study_types"] or bool(kinds.intersection(form["study_types"]))
        if not wanted:
            continue
        keys = _checklist_keys(form["name"])
        where = next((place for name, place in places if any(key in name for key in keys)), None)
        because = "every submission" if not form["study_types"] else "the draft reads as %s" % ", ".join(
            sorted(kinds.intersection(form["study_types"])))
        if where is not None:
            findings.append(Finding("reporting_checklists", "ok", "%s is in %s (%s)." % (form["name"], where, because)))
        else:
            findings.append(Finding("reporting_checklists", "fail" if form["required"] else "warn",
                                     "%s is %s and no file in the package looks like it (%s)."
                                     % (form["name"], "required" if form["required"] else "recommended", because)))
    return findings or [Finding("reporting_checklists", "ok", "no checklist applies to this study type.")]


def check_template(manuscript, guidelines):
    """6. Template or document-class conformance."""
    template = guidelines["template"]
    wanted = template["document_class"]
    if not wanted:
        return [Finding("template", "skipped", "%s names no document class%s."
                         % (guidelines["display_name"], " and links no no-login template" if not template["url"] else ""))]
    if manuscript.kind != "latex":
        return [Finding("template", "skipped", "the draft is not LaTeX; %s's class (%s) cannot be checked."
                         % (guidelines["display_name"], wanted))]
    loaded = manuscript.document_classes()
    if wanted in loaded:
        return [Finding("template", "ok", "the draft loads %s." % wanted)]
    return [Finding("template", "fail", "the draft loads %s; %s's template is %s."
                     % (", ".join(loaded) or "no class or style", guidelines["display_name"], wanted))]


def check_provenance(manuscript, guidelines, project=None):
    """7. The provenance cross-check, off the sentence pass the claim linter shares.

    What code alone can say: every tag in the draft is well formed, and, when a project is given,
    every `res` tag names an artifact in its manifest and every `ref` tag a reference it holds.
    Which untagged sentences are claims is a model call and belongs to the linter, so this counts
    them and says so rather than guessing.
    """
    findings, malformed, unresolved = [], [], []
    pass_ = manuscript.sentence_pass()
    tagged = [sentence for sentence in pass_ if sentence.tags]
    known_artifacts, known_refs, index = set(), set(), {}
    if project is not None:
        index = identifier_index(project)  # a `ref` tag may name its work by `doi:` or `arxiv:` (ticket 98)
        known_artifacts = manifest_paths(read_manifest(project))
        known_refs = {path.name for path in (Path(project) / "research" / "refs").glob("*")} | {
            path.stem for path in (Path(project) / "research" / "kb" / "nodes").glob("*.json")}
    for sentence in tagged:
        for tag in sentence.tags:
            kind, parts = parse_tag(tag)
            if parts is None:
                malformed.append(tag)
            elif project is not None and kind == "res" and parts["artifact"] not in known_artifacts:
                unresolved.append(tag)
            elif project is not None and kind == "ref" and ref_slug(parts, index) not in known_refs:
                unresolved.append(tag)
    if malformed:
        findings.append(Finding("provenance", "fail", "malformed provenance tag(s): %s." % ", ".join(sorted(set(malformed)))))
    if unresolved:
        findings.append(Finding("provenance", "fail", "provenance tag(s) that resolve to nothing: %s." % ", ".join(sorted(set(unresolved)))))
    findings.append(Finding("provenance", "ok", "%d of %d sentence(s) carry a provenance tag; the linter's classifier decides which of the other %d are claims."
                             % (len(tagged), len(pass_), len(pass_) - len(tagged))))
    return findings


def run_checks(manuscript, guidelines, project=None):
    """The seven checks, in order, off `guidelines.json` alone. Nothing here reaches the network."""
    if not isinstance(manuscript, Manuscript):
        manuscript = Manuscript(manuscript)
    if not isinstance(guidelines, dict):
        guidelines = read_guidelines(guidelines)
    findings = []
    findings.extend(check_length(manuscript, guidelines))
    findings.extend(check_structure(manuscript, guidelines))
    findings.extend(check_figures(manuscript, guidelines))
    findings.extend(check_references(manuscript, guidelines))
    findings.extend(check_reporting_checklists(manuscript, guidelines))
    findings.extend(check_template(manuscript, guidelines))
    findings.extend(check_provenance(manuscript, guidelines, project=project))
    return findings


def worst(findings):
    """The worst level in `findings`: what the writer's Type-A gate reads."""
    return max((finding.level for finding in findings), key=lambda level: LEVEL_ORDER[level], default="ok")


# --- the command ----------------------------------------------------------------------------------


def _render_build(report):
    lines = ["built %d venue(s); %d reached their own guidelines page" % (report["built"], report["reached"])]
    for venue in report["venues"]:
        lines.append("  %-22s %s  verified %d/%d  %s" % (
            venue["venue"],
            "reached " if venue["reached"] else "no reply",
            len(venue["fully_verified_fields"]), len(VERIFIED_FIELDS),
            venue["date_checked"],
        ))
    if report["unreachable"]:
        lines.append("unreachable: %s (their fields keep the research note's date and are unverified)"
                     % ", ".join(report["unreachable"]))
    return "\n".join(lines)


def _render_checks(findings):
    marks = {"ok": "ok  ", "warn": "warn", "fail": "FAIL", "skipped": "--  "}
    return "\n".join("%s %-22s %s" % (marks[finding.level], finding.check, finding.message) for finding in findings)


def build_command(args):
    """`wayline guidelines build` and `wayline guidelines check`."""
    parser = argparse.ArgumentParser(prog="wayline guidelines", description="build the venue guidelines, or check a draft against one")
    sub = parser.add_subparsers(dest="subcommand")

    builder = sub.add_parser("build", help="fetch each venue's pages and write guidelines/<venue>/")
    builder.add_argument("--venue", action="append", help="build only this venue; repeatable")
    builder.add_argument("--root", help="the harness directory to write guidelines/ into; this harness by default")
    builder.add_argument("--fixtures", help="answer every request from this directory of recorded responses instead of the network")
    builder.add_argument("--no-checklists", action="store_true", help="do not cache the reporting-checklist forms")
    builder.add_argument("--json", action="store_true", help="print the report as JSON instead of text")

    checker = sub.add_parser("check", help="run the seven mechanical checks on a drafted manuscript")
    checker.add_argument("manuscript", help="the directory (or single file) the draft lives in")
    checker.add_argument("--venue", required=True, help="the venue slug under guidelines/")
    checker.add_argument("--root", help="the harness directory guidelines/ lives in; this harness by default")
    checker.add_argument("--project", help="resolve provenance tags against this project's manifest and references")
    checker.add_argument("--json", action="store_true", help="print the findings as JSON instead of text")

    options, code = parse_args(parser, args)
    if options is None:
        return code
    root = options.root if getattr(options, "root", None) else HARNESS_ROOT
    if options.subcommand == "build":
        fetcher = recording_fetcher(options.fixtures) if options.fixtures else Fetcher()
        try:
            report = build(root=root, fetcher=fetcher, venues=options.venue, cache_checklists=not options.no_checklists)
        except (GuidelinesError, OSError, ValueError) as failure:
            print("wayline guidelines build: %s" % failure, file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2) if options.json else _render_build(report))
        return 0
    if options.subcommand == "check":
        try:
            findings = run_checks(Manuscript(options.manuscript), read_guidelines(root, options.venue), project=options.project)
        except (GuidelinesError, OSError, ValueError) as failure:
            print("wayline guidelines check: %s" % failure, file=sys.stderr)
            return 1
        if options.json:
            print(json.dumps([finding._asdict() for finding in findings], ensure_ascii=False, indent=2))
        else:
            print(_render_checks(findings))
        return 1 if worst(findings) == "fail" else 0
    parser.print_help()
    return 2
