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

## Unified cgroup v2 build on W1WEOS36.48-22-3-3-4-2

On November 20, 2026, the slot-A phone booted kernel `5.15.180` with SELinux enforcing. It listed 360 loaded modules with no unknown-symbol, symbol-version or module-verification errors in the captured kernel log.

| Check | Result |
| --- | --- |
| USB ADB and Debian | Passed. A 1 MiB USB ADB upload and readback matched byte-for-byte. All 18 Debian checks passed before and after replacing the launcher. |
| Wi-Fi | Passed for association, default routing, DNS and APT downloads. |
| Internal UFS storage | Passed for cgroup I/O accounting. In six overlapping trials, each 96 MiB writer was charged exactly 100,663,296 bytes on the mapper and the physical queue. The timings did not establish a repeatable BFQ latency improvement. |
| Display, GPU, touch | SurfaceFlinger reported Mali-G57 OpenGL ES 3.2 and Android enumerated a touchscreen. Physical input, rotation, brightness and accelerated workload testing remain open. |
| Camera, audio, codecs and DRM | Android enumerated three cameras and reported AudioFlinger, Codec2 and Widevine. Front and rear capture, microphone and speaker playback, hardware encode/decode and protected playback remain open. |
| Sensors, location, Bluetooth and fingerprint | Motion, light and proximity sensors and a GPS provider were present. Bluetooth was enabled and fingerprint service responded. Pairing, sensor response, GPS fix and fingerprint unlock remain open. |
| Cellular | Both SIM states were `NOT_READY`, and no slot reported Voice or Data In Service. The vendor radio daemon was running. Registration, voice, cellular data and messaging require a known-good active SIM and a stock comparison if registration still fails. |
| Power and external devices | Android reported USB power, a full battery and 23°C. Repeated suspend/resume, sustained thermals, NFC, MTP, OTG and tethering remain open. |

### Follow-up boot check

The phone reported Android recovery when testing resumed. One normal reboot returned to the recovery screen offering **Try again** and **Factory data reset**. After checking the connected XT2617V, active slot A and both image hashes, the operator authorized restoration of the matching stock `boot_a` and `init_boot_a`. Fastboot reported both writes successful. The first reboot returned to recovery, and recovery ADB could not read the boot logs.

The operator selected **Try again**, and stock Android then completed boot. ADB confirmed firmware `W1WEOS36.48-22-3-3-4-2`, slot A, the stock kernel, SELinux enforcing, `RUNNING_UNLOCKED` for Android user 0 and a read/write `/data` mount. No factory reset was performed.

After booting stock, Android's DropBox retained repeated `system_server` crashes. Each reported that `ProcessList.startProcess` failed to create a process group for an isolated WebView sandbox process. The saved kernel log recorded init rebooting with the `RescueParty` reason after those crashes. The retained evidence establishes the crash and reboot chain. It does not identify the native cgroup operation or errno. Before restoring the experimental cgroup policy, instrument process-group creation and exercise repeated isolated WebView starts, exits and app restarts. [Android Crash Recovery](https://source.android.com/docs/core/ota/modular-system/crash-recovery)

The bootloader rejected the original Magisk image directly. The rehearsed recovery kernel restored the verified plain Magisk image. ARM64 QEMU first verified that it wrote an exact stock-matching partition, refused a mismatched partition, and left a neighboring fixture partition byte-for-byte intact. Fastboot then restored the stock kernel. Android completed boot with SELinux enforcing, both live partition hashes matched their intended images, and ADB verified Magisk 31.1 root. The existing OTA guard was the only installed module. It was enabled and the Motorola updater was absent from the package manager and process list. The experimental cgroup overlay and the phone K3s agent are offline on this configuration.

The subsequent cgroup v2-only retry canary booted on slot A with Magisk and the OTA guard. A live trace confirmed that WebView could ask `system_server` to move a renderer before its isolated SELinux transition. The updated library retries the brief permission denial after specialization. Fifty cold WebView launches passed with the same `system_server` PID under enforcing SELinux and `cgroup_no_v1=all,named`. [WebView regression and patch order](k3s-worker-plan.md)
