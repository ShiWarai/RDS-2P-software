/* Докачиваемый загрузчик бинарных моделей (Range + потоковый прогресс).
 *
 * Модели приходят из локального образа, но сеть бывает рваной (Wi-Fi класса):
 * загрузка возобновляется с последнего полученного байта (`Range: bytes=N-`),
 * состояние (state) живёт между попытками — политику повторов задаёт вызывающая
 * сторона (см. policyRunner.js: бесконечные ретраи с бэкоффом + докачка).
 *
 * Семантика ответов:
 *   206 — докачка с ожидаемого офсета (сверяем Content-Range);
 *   200 — сервер отдал файл с начала (Range не поддержан/кэш) → начинаем заново;
 *   416 — наш офсет за концом файла (файл на сервере сменился) → начинаем заново.
 *
 * Обрыв потока (сеть/прокси) выбрасывается наружу как ошибка — полученные
 * куски остаются в state, следующая попытка продолжит с места обрыва.
 */

export async function downloadResumable(url, state, onProgress) {
  for (;;) {
    if (state.size > 0 && state.got >= state.size) { break; }

    const resp = await fetch(url, state.got > 0 ? { headers: { Range: `bytes=${state.got}-` } } : {});
    if (resp.status === 416) {
      // Файл на сервере короче нашего офсета — качаем заново.
      state.chunks = [];
      state.got = 0;
      state.size = 0;
      continue;
    }
    if (!resp.ok) {
      const err = new Error(`HTTP ${resp.status}`);
      err.status = resp.status;
      throw err;
    }

    if (resp.status === 206) {
      const m = /^bytes (\d+)-(\d+)\/(\d+|\*)$/.exec(resp.headers.get("Content-Range") || "");
      if (!m || Number(m[1]) !== state.got) {
        throw new Error("Некорректный ответ на докачку (206 без совпадающего Content-Range)");
      }
      if (m[3] !== "*") { state.size = Number(m[3]); }
    } else {
      if (resp.status !== 200) {
        throw new Error(`Неожиданный статус ответа: ${resp.status}`);
      }
      // 200 — полный файл с нуля (Range проигнорирован): прежние куски невалидны.
      state.chunks = [];
      state.got = 0;
      state.size = Number(resp.headers.get("Content-Length") || "0") || 0;
    }
    report(state, onProgress);

    if (!resp.body) {
      // Клиент без потокового body (экзотика) — забираем целиком.
      const buf = new Uint8Array(await resp.arrayBuffer());
      state.chunks = [buf];
      state.got = buf.byteLength;
      if (!state.size) { state.size = state.got; }
      report(state, onProgress);
      continue;
    }

    const reader = resp.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) { break; }
      state.chunks.push(value);
      state.got += value.byteLength;
      report(state, onProgress);
    }

    if (state.size === 0) { break; } // размер неизвестен — считаем поток полным
  }

  const out = new Uint8Array(state.got);
  let off = 0;
  for (const chunk of state.chunks) {
    out.set(chunk, off);
    off += chunk.byteLength;
  }
  return out.buffer;
}

function report(state, onProgress) {
  if (!onProgress) { return; }
  onProgress(state.size ? Math.min(0.999, state.got / state.size) : 0);
}