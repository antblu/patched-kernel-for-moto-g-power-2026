# Android hardware test checklist

Record the public device codename, firmware build, kernel release, and the result of each check. Use Passed, Failed, Skipped, Not run, or Unsupported. Mark a check Passed only after observing the expected behavior. Keep screen recordings, carrier details, test account data, and raw Android logs in private storage.

Run the checks first on the original kernel to establish what works with the device, plan, and accessories available. Repeat the same checks after any separately authorized candidate boot. An unavailable network or accessory is a reason to skip the affected check.

| Check | Expected behavior |
| --- | --- |
| Android, display, and touch | Lock screen and launcher render. Touch, rotation, brightness, and screen timeout work. |
| Wi-Fi and Bluetooth | Connect to a test network and transfer data. Pair an audio device and play sound. |
| 4G, 5G, and cellular data | Registration and data work on each radio mode supported by the test plan and coverage. |
| Voice, VoLTE, SMS, and MMS | Use a consenting test contact for calls and messages. Verify audio in both directions and receipt of each supported message type. |
| Camera, microphone, and speakers | Capture from front and rear cameras. Record sound and play it through the speaker and earpiece. |
| GPU and media | Render an accelerated application. Play and record a supported hardware-accelerated video format. |
| GPS and sensors | Verify a location fix and sensor response while keeping readings private. Check fingerprint unlock if already configured. |
| USB modes | Verify ADB and file transfer, then test a USB peripheral and tethering with the appropriate host. |
| Power and thermal | Check charging, temperature under normal load, and repeated screen-off suspend and resume. |
| Linux runtimes | Run the [kernel discovery report](../README.md), then test each intended chroot or container runtime separately. |

## PID-controller build on W1WEOS36.48-22-3-3-4-2

Android completed boot on `vegas26` with kernel `5.15.180`. ADB transferred a file over USB and read back identical bytes. Wi-Fi was associated and Debian passed DNS and APT download checks. Android reported external USB power.

The display compositor and audio service responded, cameras were enumerated, and Android reported a GNSS provider. The phone operator reported that touch and rotation, both cameras, microphone and speakers, Bluetooth pairing, fingerprint, GPS fix, cellular data, calls and texts, and screen-off suspend and wake appeared to work. Separate 4G and 5G checks, MMS and VoLTE, GPU and media workloads, USB accessories and tethering, and sustained thermal testing remain pending.

## CFS Bandwidth and Container Networking build on W1WEOS36.48-22-3-3-4-2

Android completed boot on slot A on `vegas26` with kernel release `5.15.180 #1 SMP PREEMPT Wed Nov 18 12:57:38 MST 2026`. Fastboot flashed only `boot_a` after preflight verified product, slot, and partition size matching the verified 64 MiB backup.

- **Integrity**: `sys.boot_completed=1`, SELinux stayed enforcing, root worked, and all 360 vendor modules loaded with 0 dmesg symbol errors or loader warnings.
- **CFS Bandwidth**: `/dev/cpuctl/cfs-hardware-test` applied a 10% CPU bandwidth quota (10,000 us per 100,000 us period) across two busy workers pinned to CPU 0 and CPU 1 via toybox `taskset`. The test observed 20/20 throttled periods and 3.69 seconds of accumulated throttled time (`CFS_HARDWARE_THROTTLE_PASS`).
- **Container Networking**: `tests/test-container-bridge.sh` injected table `main` lookup into policy routing (`ip rule add from all lookup main pref 9999`) and verified bidirectional packet transmission between two container namespaces across bridge `br-test0` (0.14 - 0.21 ms latency, 0% packet loss), gateway ping, and iptables NAT MASQUERADE (`CONTAINER_NETWORKING_PASS`).
- **Runtimes & Subsystems**: All 17 checks in the Debian 13 ARM64 regression suite passed. Bidirectional VXLAN packet transmission between isolated network namespaces passed. Display, battery (100%, 24°C), audio, 3 camera sensors, Wi-Fi, and real-time motion/orientation sensors remained fully functional.
