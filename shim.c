/* Android 10 compatibility shims injected into vulkan.*.so (aarch64, freestanding). */
typedef unsigned long u64;
typedef long s64;
typedef unsigned char u8;

extern char got_pthread_mutex_init[], got_pthread_cond_init[], got_pthread_create[],
            got_pthread_join[], got_pthread_self[], got___errno[];

#define GOTCALL(ret, name, args) ((ret (*) args)(*(void **)(got_##name)))

static inline s64 sys3(s64 nr, s64 a, s64 b, s64 c) {
    register s64 x8 __asm__("x8") = nr;
    register s64 x0 __asm__("x0") = a;
    register s64 x1 __asm__("x1") = b;
    register s64 x2 __asm__("x2") = c;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2) : "memory", "cc");
    return x0;
}

/* ---- C11 threads (API 30) on top of pthread ---- */
int shim_mtx_init(void *m, int type) {
    if (type & 2) { /* mtx_recursive: PTHREAD_RECURSIVE_MUTEX_INITIALIZER_NP = {0x4000} */
        u8 *p = (u8 *)m;
        for (int i = 0; i < 40; i++) p[i] = 0;
        *(int *)m = 0x4000;
        return 0;
    }
    return GOTCALL(int, pthread_mutex_init, (void *, const void *))(m, 0) ? 2 : 0;
}
int shim_cnd_init(void *c) {
    return GOTCALL(int, pthread_cond_init, (void *, const void *))(c, 0) ? 2 : 0;
}
int shim_thrd_create(void *thr, void *fn, void *arg) {
    return GOTCALL(int, pthread_create, (void *, const void *, void *, void *))(thr, 0, fn, arg) ? 2 : 0;
}
int shim_thrd_join(u64 thr, int *res) {
    void *r = 0;
    int rc = GOTCALL(int, pthread_join, (u64, void **))(thr, &r);
    if (rc) return 2;
    if (res) *res = (int)(s64)r;
    return 0;
}
void shim_thrd_yield(void) { sys3(124, 0, 0, 0); }

/* ---- API 36 / misc libc additions ---- */
static int aff_get(s64 pid, u64 size, void *set) {
    s64 r = sys3(123, pid, (s64)size, (s64)set);
    if (r < 0) return (int)-r;
    u8 *p = (u8 *)set;
    for (u64 i = (u64)r; i < size; i++) p[i] = 0;
    return 0;
}
int shim_pthread_getaffinity_np(u64 t, u64 size, void *set) { (void)t; return aff_get(0, size, set); }
int shim_pthread_setaffinity_np(u64 t, u64 size, const void *set) {
    u64 self = GOTCALL(u64, pthread_self, (void))();
    if (t != self) return 0; /* cannot map pthread_t -> tid here; pinning is best-effort */
    s64 r = sys3(122, 0, (s64)size, (s64)set);
    return r < 0 ? (int)-r : 0;
}
int shim_sched_getaffinity(int pid, u64 size, void *set) {
    int e = aff_get(pid, size, set);
    if (e) { *GOTCALL(int *, __errno, (void))() = e; return -1; }
    return 0;
}
int shim_getpwuid_r(unsigned uid, void *pwd, char *buf, u64 len, void **result) {
    (void)uid; (void)pwd; (void)buf; (void)len;
    *result = 0;
    return 2; /* ENOENT */
}

typedef int (*cmp_t)(const void *, const void *, void *);
static void swp(u8 *a, u8 *b, u64 n) { while (n--) { u8 t = *a; *a++ = *b; *b++ = t; } }
static void sift(u8 *base, u64 size, u64 root, u64 n, cmp_t cmp, void *arg) {
    for (;;) {
        u64 child = 2 * root + 1;
        if (child >= n) return;
        if (child + 1 < n && cmp(base + child * size, base + (child + 1) * size, arg) < 0) child++;
        if (cmp(base + root * size, base + child * size, arg) >= 0) return;
        swp(base + root * size, base + child * size, size);
        root = child;
    }
}
void shim_qsort_r(void *b, u64 n, u64 size, cmp_t cmp, void *arg) {
    u8 *base = (u8 *)b;
    if (n < 2 || !size) return;
    for (u64 i = n / 2; i-- > 0;) sift(base, size, i, n, cmp, arg);
    for (u64 end = n - 1; end > 0; end--) {
        swp(base, base + end * size, size);
        sift(base, size, 0, end, cmp, arg);
    }
}

/* ---- pure forwarders to the pthread equivalents (same ABI) ---- */
#define FWD(shim, got) \
    __asm__(".text\n.p2align 4\n.globl " #shim "\n.type " #shim ",@function\n" #shim ":\n" \
            "adrp x16, " #got "\n ldr x16, [x16, :lo12:" #got "]\n br x16\n")
FWD(shim_mtx_lock, got_pthread_mutex_lock);
FWD(shim_mtx_unlock, got_pthread_mutex_unlock);
FWD(shim_mtx_destroy, got_pthread_mutex_destroy);
FWD(shim_cnd_signal, got_pthread_cond_signal);
FWD(shim_cnd_broadcast, got_pthread_cond_broadcast);
FWD(shim_cnd_destroy, got_pthread_cond_destroy);
FWD(shim_cnd_wait, got_pthread_cond_wait);
FWD(shim_call_once, got_pthread_once);
FWD(shim_thrd_current, got_pthread_self);

