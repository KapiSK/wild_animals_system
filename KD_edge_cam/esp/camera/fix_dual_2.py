import re

file_path = r'c:\Users\kapib\vscodegit\wild_animals\test2\dual_cpu_project\esp\camera\camera.ino'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. sleepcfg 名前空間から configureWakeAndMaybeSleepEarly の終わりまでを削除
content = re.sub(
    r'/[\*]+\n \* 15\.  Sleep helpers\n \*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*\*/\nnamespace sleepcfg \{.*?\} // Otherwise, continue with normal operation\n\}\n',
    '',
    content,
    flags=re.DOTALL
)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Second removal complete.")
