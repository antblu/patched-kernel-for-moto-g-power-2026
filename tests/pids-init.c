/* Freestanding AArch64 init for a cgroup v2 PID-limit smoke test. */
#include <stddef.h>
#include <asm/unistd.h>
#include <linux/errno.h>
#include <linux/reboot.h>
#include <linux/signal.h>

static long syscall5(long nr, long a, long b, long c, long d, long e)
{
    register long x8 asm("x8") = nr;
    register long x0 asm("x0") = a;
    register long x1 asm("x1") = b;
    register long x2 asm("x2") = c;
    register long x3 asm("x3") = d;
    register long x4 asm("x4") = e;

    asm volatile("svc 0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4) : "memory");
    return x0;
}

#define SAY(text) syscall5(__NR_write, 1, (long)(text), sizeof(text) - 1, 0, 0)

#define OPEN(path, flags) syscall5(__NR_openat, -100, (long)(path), (flags), 0, 0)

void _start(void)
{
    long mounted = syscall5(__NR_mount, (long)"none", (long)"/cg", (long)"cgroup2", 0, 0);
    if (mounted == 0) {
        char controllers[128];
        long fd = OPEN("/cg/cgroup.controllers", 0);
        long length = syscall5(__NR_read, fd, (long)controllers, sizeof(controllers), 0, 0);
        SAY("Unified controllers in the VM: ");
        if (length > 0)
            syscall5(__NR_write, 1, (long)controllers, length, 0, 0);
        fd = OPEN("/cg/cgroup.subtree_control", 1);
        long enabled = syscall5(__NR_write, fd, (long)"+pids", 5, 0, 0);
        if (enabled == 5 && syscall5(__NR_mkdirat, -100, (long)"/cg/test", 0755, 0, 0) == 0) {
            long pids = OPEN("/cg/test/pids.max", 1);
            long procs = OPEN("/cg/test/cgroup.procs", 1);
            if (syscall5(__NR_write, pids, (long)"1", 1, 0, 0) == 1 &&
                syscall5(__NR_write, procs, (long)"0", 1, 0, 0) == 1 &&
                syscall5(__NR_clone, SIGCHLD, 0, 0, 0, 0) == -EAGAIN)
                SAY("PID_LIMIT_PASS\n");
        }
    } else {
        SAY("Mounting cgroup v2 failed.\n");
    }
    syscall5(__NR_reboot, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2,
             LINUX_REBOOT_CMD_POWER_OFF, 0, 0);
    __builtin_unreachable();
}
