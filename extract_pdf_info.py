
import os
import re

def extract_text_from_pdf(filename):
    print(f"Processing {os.path.basename(filename)}...")
    try:
        with open(filename, 'rb') as f:
            data = f.read()
        
        # Try to recover text by ignoring non-ascii or using latin1
        # PDFs often compress text streams, so raw read might fail for body,
        # but metadata/headers might be visible.
        # We will look for patterns that look like text.
        text_data = data.decode('latin-1', errors='ignore')
        
        # Simple heuristic: extract sequences of printable chars
        # We want to find the Title and Abstract
        
        clean_text = re.sub(r'[^\x20-\x7E]', '', text_data) # Keep only printable ASCII
        
        # Look for "Abstract"
        abs_idx = clean_text.find("Abstract")
        if abs_idx != -1:
            print("--- Possible Abstract Found ---")
            print(clean_text[abs_idx:abs_idx+500])
        else:
            print("No 'Abstract' keyword found in raw stream (likely compressed).")
            
        # Look for Title-like strings at the beginning (first 2000 chars)
        head = clean_text[:2000]
        # Heuristic: Uppercase words or sentences
        print("--- Header Dump ---")
        print(head[:500])
        
    except Exception as e:
        print(f"Error reading {filename}: {e}")
    print("\n" + "="*30 + "\n")

folder = r"c:\Users\kapib\vscodegit\wild_animals\test2\docs\ieice_paper_draft\参考文献"
files = [f for f in os.listdir(folder) if f.endswith('.pdf')]

for f in files:
    extract_text_from_pdf(os.path.join(folder, f))
