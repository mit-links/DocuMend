"""Helper script to create a sample test DOCX document based on user specifications."""
import os
import docx
from docx.shared import Pt, RGBColor


def generate_sample_docx(output_path: str = "tests/sample_docs/test_doc.docx") -> str:
    """Generate sample document with English, German, inline formatting, and tables."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc = docx.Document()

    # Paragraph 1: English with typo and bold inline formatting
    # "Helo, this is a test documnt"
    p1 = doc.add_paragraph()
    r1_1 = p1.add_run("Helo, this is a ")
    r1_2 = p1.add_run("test documnt")
    r1_2.bold = True

    # Paragraph 2: English with spelling errors and italic inline formatting
    # "I am writing many paragrafs, some of which have errors in speling."
    p2 = doc.add_paragraph()
    p2.add_run("I am writing many ")
    r2_err1 = p2.add_run("paragrafs")
    r2_err1.italic = True
    p2.add_run(", some of which have errors in ")
    r2_err2 = p2.add_run("speling.")
    r2_err2.italic = True

    # Paragraph 3: German sentence with typo ("beispoiel") and color
    # "Einzelne Paragraphen sind in einer anderen Sprache, zum beispoiel deutsch."
    p3 = doc.add_paragraph()
    p3.add_run("Einzelne Paragraphen sind in einer anderen Sprache, zum ")
    r3_err = p3.add_run("beispoiel")
    r3_err.bold = True
    p3.add_run(" deutsch.")

    # Table: 3 rows, 2 columns
    # | Name   | Locaton   |
    # | Peter  | Zurich    |
    # | James  | Basel     |
    table = doc.add_table(rows=3, cols=2)
    table.style = "Table Grid"

    # Header row
    hdr_cells = table.rows[0].cells
    hdr_cells[0].paragraphs[0].add_run("Name").bold = True
    hdr_cells[1].paragraphs[0].add_run("Locaton").bold = True  # Typo for Location

    # Data rows
    row1_cells = table.rows[1].cells
    row1_cells[0].paragraphs[0].text = "Peter"
    row1_cells[1].paragraphs[0].text = "Zurich"

    row2_cells = table.rows[2].cells
    row2_cells[0].paragraphs[0].text = "James"
    row2_cells[1].paragraphs[0].text = "Basel"

    doc.save(output_path)
    return output_path


if __name__ == "__main__":
    path = generate_sample_docx()
    print(f"Created sample test document at: {path}")
