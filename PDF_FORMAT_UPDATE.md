# Professional PDF layout update

The proposal PDF export has been redesigned with a consistent A4 layout, branded heading, readable typography, a repeatable service table header, shaded totals, page numbering, and a two-column acceptance/signature section. Currency is rendered as `INR` in the PDF to avoid missing-font square glyphs.

To apply, replace the existing `pd_work/app.py` in your project with this version and redeploy. No database migration is required.
