#ifndef RNNOISE_AUDIO_FILTERS_OS_SUPPORT_STUB_H_
#define RNNOISE_AUDIO_FILTERS_OS_SUPPORT_STUB_H_
/*
 * Minimal os_support for Xiph rnnoise v0.x: upstream vec Neon/scalar pulls
 * <os_support.h> from Opus but the release tarball excludes it.
 * Macros match Opus conventions (opus_types.h bundled with rnnoise).
 */
#include <stddef.h>
#include <string.h>

#include "opus_types.h"

#ifndef OPUS_INLINE
#define OPUS_INLINE static inline
#endif

#ifndef OVERRIDE_OPUS_CLEAR
#define OPUS_CLEAR(dst, n) (memset((dst), 0, (size_t)(n) * sizeof(*(dst))))
#endif

#ifndef MIN32
#define MIN32(a, b) (((a) < (b)) ? (a) : (b))
#endif
#ifndef MAX32
#define MAX32(a, b) (((a) > (b)) ? (a) : (b))
#endif

#endif /* RNNOISE_AUDIO_FILTERS_OS_SUPPORT_STUB_H_ */
