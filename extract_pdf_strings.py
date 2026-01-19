
import os
import re

def extract_strings(filename, min_len=10, max_len=100):
    with open(filename, 'rb') as f:
        content = f.read()
    # Find sequence of printable characters
    regex = rb"[a-zA-Z0-9\s\.\,\-\:\(\)]{" + str(min_len).encode() + rb"," + str(max_len).encode() + rb"}"
    matches = re.findall(regex, content)
    # Decode and filter
    strings = []
    for m in matches[:100]: # First 100 matches
        try:
            s = m.decode('utf-8', errors='ignore').strip()
            if len(s) > min_len:
                strings.append(s)
        except:
            pass
    return strings

folder = r"c:\Users\kapib\vscodegit\wild_animals\test2\docs\ieice_paper_draft\参考文献"
files = [
    "2020_IEICE_Trans_Saito.pdf",
    "2509.20318v2 (1).pdf",
    "36_152.pdf",
    "computers-14-00307-v2.pdf",
    "smc2024.pdf"
]

for file in files:
    print(f"--- {file} ---")
    path = os.path.join(folder, file)
    if os.path.exists(path):
        strs = extract_strings(path, min_len=15) # Longer min_len to avoid garbage
        # Print first few likely title candidates
        for s in strs[:20]:
            print(s)
    else:
        print("File not found.")
    print("\n")
