import sys
from pathlib import Path


def replace(path, old, new, what):
    file = Path(path)
    text = file.read_text()
    if new in text:
        print(f'{path}: {what} already present upstream')
        return
    if old not in text:
        sys.exit(f'{path}: anchor missing for {what}')
    text = text.replace(old, new, 1)
    if file.suffix == '.py':
        compile(text, path, 'exec')
    file.write_text(text)
    print(f'{path}: {what}')
