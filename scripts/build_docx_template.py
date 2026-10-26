"""Rebuilds the bundled one-page, visibly demo-only Word template.

Run: python -m scripts.build_docx_template
"""
from pathlib import Path
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / 'templates' / 'wezwanie_demo.docx'
NAVY = RGBColor(24, 43, 64)
TEAL = RGBColor(29, 107, 128)
GRAY = RGBColor(82, 94, 107)


def apply_cell_shading(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), fill)
    tcPr.append(shd)


def add_cell_text(cell, text, bold=False, color=GRAY, size=9):
    p=cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.space_before = Pt(0)
    r=p.add_run(text)
    r.bold=bold
    r.font.size=Pt(size)
    r.font.color.rgb=color
    return p


def generate():
    TARGET.parent.mkdir(exist_ok=True, parents=True)
    doc=Document()
    section=doc.sections[0]
    section.page_height=Cm(29.7)
    section.page_width=Cm(21)
    section.left_margin=Cm(2.3)
    section.right_margin=Cm(2.3)
    section.top_margin=Cm(2.2)
    section.bottom_margin=Cm(2.05)
    section.header_distance=Cm(1.0)
    section.footer_distance=Cm(1.15)

    normal = doc.styles['Normal']
    normal.font.name='Aptos'
    normal.font.size=Pt(10.5)
    normal.font.color.rgb=NAVY
    normal.paragraph_format.space_after=Pt(7)
    normal.paragraph_format.line_spacing=1.15

    hdr=section.header.paragraphs[0]
    hdr.alignment=WD_ALIGN_PARAGRAPH.LEFT
    h1=hdr.add_run('LEGAL DOCUMENT ENGINE')
    h1.bold=True
    h1.font.size=Pt(8)
    h1.font.color.rgb=TEAL
    h2=hdr.add_run('     •     PORTFOLIO DEMO')
    h2.font.size=Pt(8)
    h2.font.color.rgb=GRAY

    warning=doc.add_paragraph()
    warning.paragraph_format.space_after=Pt(10)
    run=warning.add_run('PROJEKT DEMONSTRACYJNY  /  DANE WYŁĄCZNIE SYNTETYCZNE')
    run.bold=True
    run.font.size=Pt(9)
    run.font.color.rgb=TEAL

    title=doc.add_paragraph()
    title.paragraph_format.space_after=Pt(2)
    t=title.add_run('WEZWANIE DO ZAPŁATY')
    t.bold=True
    t.font.size=Pt(21)
    t.font.color.rgb=NAVY

    subtitle=doc.add_paragraph()
    subtitle.paragraph_format.space_after=Pt(17)
    r=subtitle.add_run('Wzór fikcyjny — dokument niewywołujący skutków prawnych')
    r.italic=True
    r.font.size=Pt(9)
    r.font.color.rgb=GRAY

    data=[
      ('Data sporządzenia','{{ issue_date }}'),
      ('Identyfikator demonstracyjny','{{ case_reference }}'),
      ('Fikcyjny adresat','{{ debtor }}'),
      ('Testowa faktura','{{ invoice }}'),
      ('Kwota roszczenia (demo)','{{ amount }}'),
      ('Data wymagalności (demo)','{{ due_date }}'),
    ]
    table=doc.add_table(rows=len(data),cols=2)
    table.autofit=False
    table.alignment=WD_TABLE_ALIGNMENT.CENTER
    table.columns[0].width=Cm(6.0)
    table.columns[1].width=Cm(10.2)
    for i,(label,value) in enumerate(data):
        l,r=table.rows[i].cells
        l.width=Cm(6)
        r.width=Cm(10.2)
        for cell in (l,r):
            cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if i%2==0: apply_cell_shading(cell,'F1F5F7')
        add_cell_text(l,label,bold=True,color=GRAY,size=9)
        add_cell_text(r,value,bold=False,color=NAVY,size=10)
    doc.add_paragraph().paragraph_format.space_after=Pt(0)

    h=doc.add_paragraph()
    h.paragraph_format.space_after=Pt(5)
    rr=h.add_run('Opis fikcyjnego stanu faktycznego')
    rr.bold=True
    rr.font.size=Pt(12)
    rr.font.color.rgb=TEAL

    p=doc.add_paragraph()
    p.paragraph_format.space_after=Pt(10)
    p.paragraph_format.line_spacing=1.22
    p.add_run('{{ narrative }}')

    h=doc.add_paragraph()
    h.paragraph_format.space_after=Pt(5)
    rr=h.add_run('Przykładowa treść wezwania')
    rr.bold=True
    rr.font.size=Pt(12)
    rr.font.color.rgb=TEAL

    p=doc.add_paragraph(
      'W przedstawionym wyłącznie na potrzeby demonstracji stanie faktycznym '
      'wzywa się fikcyjnego adresata do dobrowolnego uregulowania wskazanej '
      'kwoty w terminie 14 dni od otrzymania pisma. Zapis ten jest częścią '
      'wzoru testowego i nie wynika z oceny rzeczywistego roszczenia.'
    )
    p.paragraph_format.space_after=Pt(12)

    p=doc.add_paragraph()
    p.paragraph_format.space_after=Pt(3)
    r=p.add_run('Fikcyjny wystawca: ') 
    r.bold=True
    p.add_run('Podmiot Demonstracyjny (nieistniejący)')
    p=doc.add_paragraph()
    r=p.add_run('Podpis: ') 
    r.bold=True
    p.add_run('— dokument wygenerowany automatycznie (demo) —')

    p=doc.add_paragraph()
    p.paragraph_format.space_before=Pt(9)
    p.paragraph_format.space_after=Pt(0)
    r=p.add_run('UWAGA: Nie używać w rzeczywistych sprawach. Treść AI oraz dane wejściowe wymagają weryfikacji człowieka.')
    r.italic=True
    r.font.size=Pt(8.5)
    r.font.color.rgb=GRAY

    f=section.footer.paragraphs[0]
    f.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r=f.add_run('LEGAL DOCUMENT ENGINE  •  MVP v1.0  •  WYŁĄCZNIE DEMONSTRACJA')
    r.font.size=Pt(8)
    r.font.color.rgb=GRAY
    doc.save(TARGET)
    print(f'Utworzono: {TARGET}')


if __name__=='__main__':
    generate()
