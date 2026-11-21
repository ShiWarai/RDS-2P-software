"""Install browser Laya and Russian Vosk assets without Bash or Docker."""
from pathlib import Path
import urllib.request, json, zipfile, tarfile, io
ROOT = Path(__file__).resolve().parents[1]
def download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size > 0:
        print('Already installed:', target.name, flush=True); return
    partial = target.with_suffix(target.suffix + '.part')
    print('Downloading:', target.name, flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, partial.open('wb') as output:
        while chunk := response.read(1024 * 1024): output.write(chunk)
    partial.replace(target)
    print('Installed:', target.name, target.stat().st_size, flush=True)
def main():
    laya = ROOT / 'models/laya'
    for name in ['tokenizer.json', 'temperature.json']:
        download('https://huggingface.co/ShiWarai/laya-multilingual-rknn/resolve/main/' + name, laya / name)
    download('https://huggingface.co/mizchi/laya-multilingual-onnx/resolve/main/model.onnx', laya / 'model.onnx')
    (laya / 'manifest.json').write_text(json.dumps(dict(file='model.onnx', inputs='int64', tokenizer='tokenizer.json', temperature='temperature.json', seq=512, kmax=64), indent=2), encoding='utf-8')
    stt = ROOT / 'models/stt'; archive = stt / 'vosk-ru-small.tar.gz'
    archive_ok = False
    if archive.is_file():
        try:
            with tarfile.open(archive) as existing:
                archive_ok = any(entry.isdir() for entry in existing.getmembers())
        except tarfile.TarError:
            pass
    if not archive_ok:
        source = stt / 'vosk-model-small-ru-0.22.zip'
        download('https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip', source)
        partial = archive.with_suffix('.gz.part')
        with zipfile.ZipFile(source) as zipped, tarfile.open(partial, 'w:gz', format=tarfile.GNU_FORMAT) as tar:
            for entry in zipped.infolist():

                info = tarfile.TarInfo(entry.filename); info.size = entry.file_size
                info.mode = 0o755 if entry.is_dir() else 0o644
                if entry.is_dir():
                    info.type = tarfile.DIRTYPE; info.size = 0; tar.addfile(info); continue
                with zipped.open(entry) as content: tar.addfile(info, content)
        partial.replace(archive)
    print('Laya and Vosk installed. Reload http://localhost:8080/', flush=True)
if __name__ == '__main__': main()
