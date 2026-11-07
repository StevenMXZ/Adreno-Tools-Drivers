/*
 * Mesa 3-D graphics library
 * SPDX-License-Identifier: MIT
 */

/*
 * IMapper5 stable-C backend, reached via the SP-HAL loader.
 *
 * The existing IMapper backends (u_gralloc_imapper{4,5}_api.cpp) go through
 * libui's C++ GraphicBufferMapper, so they need dep_android_ui / dep_android_mapper4.
 * A Mesa built with -Dandroid-stub=true never even probes for those (meson.build
 * pins them to null_dep), so a driver loaded into an app process — adrenotools,
 * emulators, Winlator-likes — always lands on u_gralloc_fallback.c and loses
 * YCbCr support, the real modifier, and the dataspace.
 *
 * libui itself reaches the vendor mapper through AIMapper_loadIMapper(), a plain
 * C entry point that android_load_sphal_library() can resolve from a non-vendor
 * process. This backend does that directly, so it needs only dlopen/dlsym.
 */

#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <inttypes.h>
#include <stdalign.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "drm-uapi/drm_fourcc.h"
#include "util/log.h"
#include "util/u_memory.h"

#include "u_gralloc_internal.h"

/* ---------------------------------------------------------------------------
 * AIMapper ABI. Mirrors AOSP IMapper.h; member order is load-bearing, so the
 * unused tail is kept (as void *) rather than truncated.
 * --------------------------------------------------------------------------- */

typedef struct AIMapperV5 {
   void *importBuffer;
   void *freeBuffer;
   void *getTransportSize;
   void *lock;
   void *unlock;
   void *flushLockedBuffer;
   void *rereadLockedBuffer;
   void *getMetadata;
   int32_t (*getStandardMetadata)(const native_handle_t *buffer,
                                  int64_t standardMetadataType, void *destBuffer,
                                  size_t destBufferSize);
   void *setMetadata;
   void *setStandardMetadata;
   void *listSupportedMetadataTypes;
   void *dumpBuffer;
   void *dumpAllBuffers;
   void *getReservedRegion;
} AIMapperV5;

typedef struct AIMapper {
   alignas(alignof(max_align_t)) uint32_t version;
   AIMapperV5 v5;
} AIMapper;

#define AIMAPPER_VERSION_5 5

/* StandardMetadataType.aidl */
#define SMT_LAYER_COUNT           5
#define SMT_PIXEL_FORMAT_FOURCC  7
#define SMT_PIXEL_FORMAT_MODIFIER 8
#define SMT_ALLOCATION_SIZE      10
#define SMT_COMPRESSION          12
#define SMT_CHROMA_SITING        14
#define SMT_PLANE_LAYOUTS        15
#define SMT_DATASPACE            17

/* Dataspace bit fields */
#define DS_STANDARD_MASK  (63u << 16)
#define DS_STANDARD_BT709 (1u << 16)
#define DS_STANDARD_BT2020        (6u << 16)
#define DS_STANDARD_BT2020_CL     (7u << 16)
#define DS_RANGE_MASK    (7u << 27)
#define DS_RANGE_FULL    (1u << 27)

/* ChromaSiting.aidl */
#define CHROMA_SITING_COSITED_HORIZONTAL 3
#define CHROMA_SITING_COSITED_VERTICAL   4
#define CHROMA_SITING_COSITED_BOTH       5

struct aimapper_gralloc {
   struct u_gralloc base;
   void *mapper_lib;
   AIMapper *mapper;
};

/* ---------------------------------------------------------------------------
 * Metadata decoding.
 *
 * Every value is framed: an int64 name length, the type-name bytes, an int64
 * type id, then the payload. Nothing is padded, so the payload is not naturally
 * aligned — read through memcpy only.
 * --------------------------------------------------------------------------- */

struct md_reader {
   const uint8_t *p;
   const uint8_t *end;
   bool ok;
};

static bool
md_take(struct md_reader *r, void *dst, size_t n)
{
   if (!r->ok || (size_t)(r->end - r->p) < n) {
      r->ok = false;
      return false;
   }
   if (dst)
      memcpy(dst, r->p, n);
   r->p += n;
   return true;
}

static int64_t
md_i64(struct md_reader *r)
{
   int64_t v = 0;
   md_take(r, &v, sizeof(v));
   return v;
}

/* Copies a length-prefixed string out, NUL-terminated and truncated to fit. */
static void
md_take_str(struct md_reader *r, char *out, size_t out_size)
{
   int64_t len = md_i64(r);
   if (len < 0 || len > (r->end - r->p)) {
      r->ok = false;
      if (out_size)
         out[0] = '\0';
      return;
   }
   size_t copy = (size_t) len < out_size - 1 ? (size_t) len : out_size - 1;
   if (out_size) {
      memcpy(out, r->p, copy);
      out[copy] = '\0';
   }
   md_take(r, NULL, (size_t) len);
}

/* Skips a length-prefixed string. */
static void
md_skip_str(struct md_reader *r)
{
   int64_t len = md_i64(r);
   if (len < 0 || len > (r->end - r->p)) {
      r->ok = false;
      return;
   }
   md_take(r, NULL, (size_t)len);
}

/* Consumes the [name][type] frame and checks the type id matches. */
static bool
md_header(struct md_reader *r, int64_t expect_type)
{
   md_skip_str(r);
   return r->ok && md_i64(r) == expect_type && r->ok;
}

/* Fetches one metadata value into buf. Returns payload byte count, or < 0. */
static int32_t
md_fetch(struct aimapper_gralloc *gr, const native_handle_t *handle,
         int64_t type, void *buf, size_t buf_size)
{
   int32_t n = gr->mapper->v5.getStandardMetadata(handle, type, buf, buf_size);
   if (n < 0 || (size_t)n > buf_size)
      return -1;
   return n;
}

/* Scalars are small; one stack buffer covers header + value comfortably. */
static bool
md_scalar(struct aimapper_gralloc *gr, const native_handle_t *handle,
          int64_t type, void *out, size_t out_size)
{
   uint8_t buf[160];
   int32_t n = md_fetch(gr, handle, type, buf, sizeof(buf));
   if (n < 0)
      return false;

   struct md_reader r = {buf, buf + n, true};
   if (!md_header(&r, type))
      return false;

   return md_take(&r, out, out_size);
}

/* ---------------------------------------------------------------------------
 * ops
 * --------------------------------------------------------------------------- */

/* Reads StandardMetadataType::COMPRESSION, an ExtendableType (name + value).
 * Returns true if the mapper answered, filling name/value. This is the standard,
 * vendor-neutral way to ask whether a buffer is compressed - preferable to
 * inferring it from the plane layout, provided the vendor actually populates it.
 */
static bool
md_compression(struct aimapper_gralloc *gr, const native_handle_t *handle,
               char *name, size_t name_size, int64_t *value)
{
   uint8_t buf[256];
   int32_t n = md_fetch(gr, handle, SMT_COMPRESSION, buf, sizeof(buf));
   if (n < 0)
      return false;

   struct md_reader r = {buf, buf + n, true};
   if (!md_header(&r, SMT_COMPRESSION))
      return false;

   md_take_str(&r, name, name_size);
   *value = md_i64(&r);

   return r.ok;
}

static int
aimapper_get_buffer_basic_info(struct u_gralloc *gralloc,
                               struct u_gralloc_buffer_handle *hnd,
                               struct u_gralloc_buffer_basic_info *out)
{
   struct aimapper_gralloc *gr = (struct aimapper_gralloc *)gralloc;

   if (!hnd->handle) {
      mesa_logw("aimapper: FAIL null handle");
      return -EINVAL;
   }

   uint32_t fourcc = 0;
   if (!md_scalar(gr, hnd->handle, SMT_PIXEL_FORMAT_FOURCC, &fourcc,
                  sizeof(fourcc))) {
      mesa_logw("aimapper: PIXEL_FORMAT_FOURCC unavailable");
      return -EINVAL;
   }

   /* QTI's mapper returns 0 for some buffers (observed on UBWC swapchain
    * images) even though the query succeeds. Derive it from the HAL format
    * instead, which is what the legacy backends always did.
    */
   if (fourcc == 0) {
      int derived = get_fourcc_from_hal_format(hnd->hal_format);
      if (derived == -1) {
         mesa_logw("aimapper: no fourcc from mapper and none for hal_format %d",
                   hnd->hal_format);
         return -EINVAL;
      }
      fourcc = (uint32_t) derived;
   }

   out->drm_fourcc = fourcc;

   uint64_t modifier = 0;
   if (md_scalar(gr, hnd->handle, SMT_PIXEL_FORMAT_MODIFIER, &modifier,
                 sizeof(modifier)))
      out->modifier = modifier;
   else
      out->modifier = DRM_FORMAT_MOD_INVALID;

   /* Plane layouts: [numPlanes] then per plane [numComponents]
    * [component: name-string, int64 offsetInBits, int64 sizeInBits] * n
    * followed by 8 int64 plane fields, of which we want offsetInBytes and
    * strideInBytes.
    */
   int32_t need = gr->mapper->v5.getStandardMetadata(hnd->handle,
                                                     SMT_PLANE_LAYOUTS, NULL, 0);
   if (need <= 0) {
      mesa_logw("aimapper: PLANE_LAYOUTS unavailable (%d)", need);
      return -EINVAL;
   }

   /* Everything the gotos skip past is declared up front, so no jump crosses an
    * initialisation.
    */
   uint8_t *buf = NULL;
   int ret = -EINVAL;
   int32_t got = 0;
   int64_t num_planes = 0;
   struct md_reader r = {NULL, NULL, false};

   buf = MALLOC(need);
   if (!buf) {
      mesa_logw("aimapper: FAIL malloc %d", need);
      return -ENOMEM;
   }

   got = md_fetch(gr, hnd->handle, SMT_PLANE_LAYOUTS, buf, need);
   if (got < 0) {
      mesa_logw("aimapper: FAIL PLANE_LAYOUTS fetch (need=%d got=%d)", need, got);
      goto out_free;
   }

   r = (struct md_reader){buf, buf + got, true};
   if (!md_header(&r, SMT_PLANE_LAYOUTS)) {
      mesa_logw("aimapper: FAIL PLANE_LAYOUTS header framing (%d bytes)", got);
      goto out_free;
   }

   num_planes = md_i64(&r);
   if (!r.ok || num_planes <= 0 || num_planes > 4) {
      mesa_logw("aimapper: implausible plane count %" PRId64, num_planes);
      goto out_free;
   }

   for (int64_t i = 0; i < num_planes && r.ok; i++) {
      int64_t num_components = md_i64(&r);
      if (!r.ok || num_components < 0 || num_components > 16) {
         mesa_logw("aimapper: FAIL plane %" PRId64 " component count %" PRId64
                   " (ok=%d)", i, num_components, (int) r.ok);
         goto out_free;
      }

      for (int64_t j = 0; j < num_components && r.ok; j++) {
         md_skip_str(&r);   /* component type name */
         md_i64(&r);        /* component type value */
         md_i64(&r);        /* offsetInBits */
         md_i64(&r);        /* sizeInBits */
      }

      int64_t offset_bytes = md_i64(&r);
      md_i64(&r);                            /* sampleIncrementInBits */
      int64_t stride_bytes = md_i64(&r);
      md_i64(&r);                            /* widthInSamples */
      md_i64(&r);                            /* heightInSamples */
      md_i64(&r);                            /* totalSizeInBytes */
      md_i64(&r);                            /* horizontalSubsampling */
      md_i64(&r);                            /* verticalSubsampling */

      if (!r.ok) {
         mesa_logw("aimapper: FAIL plane %" PRId64 " field decode ran short", i);
         goto out_free;
      }

      out->offsets[i] = (int)offset_bytes;
      out->strides[i] = (int)stride_bytes;
   }

   out->num_planes = (int)num_planes;

   /* QTI's mapper describes a UBWC buffer as TWO planes with the metadata plane
    * FIRST in the allocation (offset 0) and the pixel data after it, while
    * reporting modifier LINEAR regardless. Mesa's generic path then rejects the
    * buffer as disjoint, because it treats any plane n>0 sitting at offset 0 as
    * a separate allocation (vk_android.c vk_gralloc_to_drm_explicit_layout).
    *
    * Observed on an A840, 1216x2688 RGBA8888:
    *   plane[0] offset=86016 stride=4864   <- data (4864 = 1216 * 4)
    *   plane[1] offset=0     stride=128    <- UBWC metadata (128 * 672 = 86016)
    *
    * Collapse it to the single-plane compressed description the legacy backends
    * produced and that Turnip already lays out correctly for itself.
    */
   char compr_name[128] = "";
   int64_t compr_value = 0;
   bool have_compr = md_compression(gr, hnd->handle, compr_name,
                                    sizeof(compr_name), &compr_value);

   /* Standard metadata first. "android.hardware.graphics.common.Compression"
    * with value 0 is NONE; any other name is a vendor compression scheme.
    */
   bool compr_says_compressed =
      have_compr &&
      (compr_value != 0 ||
       strcmp(compr_name,
              "android.hardware.graphics.common.Compression") != 0);

   /* Fallback: QTI's mapper has already been observed lying about this buffer
    * (modifier=LINEAR, fourcc=0 on a demonstrably UBWC allocation), so if the
    * standard query is unhelpful, fall back to the layout signature.
    */
   bool layout_says_ubwc =
      num_planes == 2 && out->offsets[1] == 0 && out->offsets[0] > 0 &&
      out->strides[1] < out->strides[0];

   if (compr_says_compressed || layout_says_ubwc) {
      /* The one observable sign that the whole UBWC path fired. Without it the
       * only way to tell a working driver from one that quietly fell back is to
       * look at the screen, which reads the same for several different faults.
       */
      mesa_logi("aimapper: compressed layout detected via %s (meta stride=%d @%d, "
                "data stride=%d @%d) - collapsing to 1 compressed plane",
                compr_says_compressed ? "COMPRESSION metadata" : "plane signature",
                out->strides[1], out->offsets[1], out->strides[0], out->offsets[0]);

      out->offsets[0] = 0;
      out->offsets[1] = 0;
      out->strides[1] = 0;
      out->num_planes = 1;
      num_planes = 1;
      out->modifier = DRM_FORMAT_MOD_QCOM_COMPRESSED;
   }

   /* Plane layouts carry no fds. Mirror the other backends: one fd shared by
    * every plane, or one fd per plane when the handle provides them.
    */
   if (hnd->handle->numFds == 0) {
      mesa_logw("aimapper: FAIL handle has no fds");
      goto out_free;
   }

   if (hnd->handle->numFds >= num_planes) {
      for (int64_t i = 0; i < num_planes; i++)
         out->fds[i] = hnd->handle->data[i];
   } else {
      for (int64_t i = 0; i < num_planes; i++)
         out->fds[i] = hnd->handle->data[0];
   }

   /* vk_gralloc_to_drm_explicit_layout() derives a multi-layer image's
    * arrayPitch from alloc_size / layer_count (mesa b3bb742f, d850d2ef). It
    * only does so when layer_count > 1 && alloc_size > 0, so leaving these at
    * zero when the mapper declines to answer is safe - it just falls back to
    * the single-layer path.
    */
   uint64_t layer_count = 0;
   if (md_scalar(gr, hnd->handle, SMT_LAYER_COUNT, &layer_count,
                 sizeof(layer_count)))
      out->layer_count = layer_count;

   uint64_t alloc_size = 0;
   if (md_scalar(gr, hnd->handle, SMT_ALLOCATION_SIZE, &alloc_size,
                 sizeof(alloc_size)))
      out->alloc_size = alloc_size;

   ret = 0;

out_free:
   FREE(buf);
   return ret;
}

static int
aimapper_get_buffer_color_info(struct u_gralloc *gralloc,
                               struct u_gralloc_buffer_handle *hnd,
                               struct u_gralloc_buffer_color_info *out)
{
   struct aimapper_gralloc *gr = (struct aimapper_gralloc *)gralloc;

   if (!hnd->handle)
      return -EINVAL;

   /* Defaults match u_gralloc.c's when a backend has no color op at all. */
   out->yuv_color_space = __DRI_YUV_COLOR_SPACE_ITU_REC601;
   out->sample_range = __DRI_YUV_NARROW_RANGE;
   out->horizontal_siting = __DRI_YUV_CHROMA_SITING_0_5;
   out->vertical_siting = __DRI_YUV_CHROMA_SITING_0_5;

   uint32_t dataspace = 0;
   if (md_scalar(gr, hnd->handle, SMT_DATASPACE, &dataspace,
                 sizeof(dataspace))) {
      switch (dataspace & DS_STANDARD_MASK) {
      case DS_STANDARD_BT709:
         out->yuv_color_space = __DRI_YUV_COLOR_SPACE_ITU_REC709;
         break;
      case DS_STANDARD_BT2020:
      case DS_STANDARD_BT2020_CL:
         out->yuv_color_space = __DRI_YUV_COLOR_SPACE_ITU_REC2020;
         break;
      default:
         break;
      }

      if ((dataspace & DS_RANGE_MASK) == DS_RANGE_FULL)
         out->sample_range = __DRI_YUV_FULL_RANGE;
   }

   /* ChromaSiting is an ExtendableType: a name string then an int64 value. */
   uint8_t buf[160];
   int32_t n = md_fetch(gr, hnd->handle, SMT_CHROMA_SITING, buf, sizeof(buf));
   if (n > 0) {
      struct md_reader r = {buf, buf + n, true};
      if (md_header(&r, SMT_CHROMA_SITING)) {
         md_skip_str(&r); /* ExtendableType.name */
         int64_t siting = md_i64(&r);
         if (r.ok) {
            switch (siting) {
            case CHROMA_SITING_COSITED_HORIZONTAL:
               out->horizontal_siting = __DRI_YUV_CHROMA_SITING_0;
               break;
            case CHROMA_SITING_COSITED_VERTICAL:
               out->vertical_siting = __DRI_YUV_CHROMA_SITING_0;
               break;
            case CHROMA_SITING_COSITED_BOTH:
               out->horizontal_siting = __DRI_YUV_CHROMA_SITING_0;
               out->vertical_siting = __DRI_YUV_CHROMA_SITING_0;
               break;
            default:
               break;
            }
         }
      }
   }

   return 0;
}

static int
destroy(struct u_gralloc *gralloc)
{
   struct aimapper_gralloc *gr = (struct aimapper_gralloc *)gralloc;

   /* The mapper is owned by the vendor library; only the handle is ours.
    * Leave it loaded — unloading an SP-HAL under a live driver is not worth
    * the risk for a process-lifetime singleton.
    */
   FREE(gr);

   return 0;
}

/* ---------------------------------------------------------------------------
 * create
 * --------------------------------------------------------------------------- */

typedef void *(*sphal_load_fn)(const char *name, int flag);
typedef int32_t (*load_imapper_fn)(AIMapper **outImplementation);

/* The platform asks IAllocator for the mapper suffix. Binder is far too heavy a
 * dependency here, so enumerate the vendor HAL directory instead.
 */
static void *
load_vendor_mapper(sphal_load_fn sphal, load_imapper_fn *out_load)
{
   static const char *const dirs[] = {"/vendor/lib64/hw", "/vendor/lib/hw"};

   for (unsigned d = 0; d < ARRAY_SIZE(dirs); d++) {
      DIR *dir = opendir(dirs[d]);
      if (!dir)
         continue;

      struct dirent *ent;
      while ((ent = readdir(dir))) {
         if (strncmp(ent->d_name, "mapper.", 7) != 0)
            continue;
         size_t len = strlen(ent->d_name);
         if (len < 4 || strcmp(ent->d_name + len - 3, ".so") != 0)
            continue;

         void *lib = sphal(ent->d_name, RTLD_NOW);
         if (!lib)
            continue;

         load_imapper_fn fn =
            (load_imapper_fn)dlsym(lib, "AIMapper_loadIMapper");
         if (fn) {
            closedir(dir);
            *out_load = fn;
            return lib;
         }
      }
      closedir(dir);
   }

   return NULL;
}

struct u_gralloc *
u_gralloc_aimapper_create(void)
{
   /* libvndksupport is the sanctioned route for a non-vendor process to load a
    * same-process vendor HAL; the Android Vulkan loader uses it for exactly
    * this. Without it we have no business touching /vendor libraries.
    */
   void *vndk = dlopen("libvndksupport.so", RTLD_NOW);
   if (!vndk)
      return NULL;

   sphal_load_fn sphal =
      (sphal_load_fn)dlsym(vndk, "android_load_sphal_library");
   if (!sphal)
      return NULL;

   load_imapper_fn load = NULL;
   void *lib = load_vendor_mapper(sphal, &load);
   if (!lib)
      return NULL;

   AIMapper *mapper = NULL;
   if (load(&mapper) != 0 || !mapper)
      return NULL;

   if (mapper->version < AIMAPPER_VERSION_5) {
      mesa_logw("aimapper: version %u is below 5, declining", mapper->version);
      return NULL;
   }

   if (!mapper->v5.getStandardMetadata)
      return NULL;

   struct aimapper_gralloc *gr = CALLOC_STRUCT(aimapper_gralloc);
   if (!gr)
      return NULL;

   gr->mapper_lib = lib;
   gr->mapper = mapper;

   gr->base.ops.get_buffer_basic_info = aimapper_get_buffer_basic_info;
   gr->base.ops.get_buffer_color_info = aimapper_get_buffer_color_info;
   gr->base.ops.destroy = destroy;

   mesa_logi("Using IMapper v5 stable-C API via SP-HAL");

   return &gr->base;
}
