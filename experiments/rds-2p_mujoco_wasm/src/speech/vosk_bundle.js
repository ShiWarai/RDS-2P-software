// vosk-browser 0.0.8 treats optional IndexedDB persistence as a fatal load error.
// Patch only the write-back step; extraction/model errors still propagate.
export function prepareVoskBundle(source) {
  return source.replace(/(WorkerFactory = createBase64WorkerFactory\(')([^']+)(')/,
    (_, prefix, encoded, suffix) => {
      const worker = atob(encoded);
      const needle = 'return this.Vosk.syncFilesystem(false);';
      if (!worker.includes(needle)) throw new Error('Unsupported vosk-browser worker version');
      const patched = worker.replace(needle,
        'return this.Vosk.syncFilesystem(false).catch(error => { this.logger.warn("Optional model cache unavailable", error); });');
      return prefix + btoa(patched) + suffix;
    });
}
