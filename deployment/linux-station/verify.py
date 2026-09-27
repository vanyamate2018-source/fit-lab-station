import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
for name,digest in json.loads((root/'checksums.json').read_text()).items():
    if Path(name).name != name or hashlib.sha256((root/name).read_bytes()).hexdigest() != digest:
        raise SystemExit('Ошибка проверки комплекта: '+name)
print('Файлы комплекта проверены')
