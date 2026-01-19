
import os
from pypdf import PdfReader

folder = r"c:\Users\kapib\vscodegit\wild_animals\test2\docs\ieice_paper_draft\参考文献"
files = [f for f in os.listdir(folder) if f.endswith('.pdf')]


with open("pdf_summary.txt", "w", encoding="utf-8") as outfile:
    for file in files:
        path = os.path.join(folder, file)
        outfile.write(f"### FILE: {file}\n")
        try:
            reader = PdfReader(path)
            page = reader.pages[0]
            text = page.extract_text()
            outfile.write(text[:2000] + "\n")
        except Exception as e:
            outfile.write(f"Error reading {file}: {e}\n")
        outfile.write("\n" + "="*40 + "\n\n")

