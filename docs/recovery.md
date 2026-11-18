# Install and recover on vegas26

These steps worked on the Moto G Power 2026 running Android 16 build W1WEOS36.48-22-3-3-4-2, with an already-unlocked bootloader and rooted Android on slot A. Verify those conditions, the candidate build manifest, and the vendor CRC results first. Back up user data and keep images in a private directory outside the checkout.

This procedure and its candidate image are specific to that device and firmware. Users of other devices or firmware must build and verify their own image and recovery procedure; do not flash this candidate image on a different target.

1. In a Linux shell with a working ADB connection, save the active 64 MiB stock boot partition and compare the two SHA-256 digests.

   ```sh
   (set -C; umask 077; adb exec-out "su -c 'dd if=/dev/block/by-name/boot_a bs=1M count=64 2>/dev/null'" > stock-boot-a.img)
   adb shell "su -c 'sha256sum /dev/block/by-name/boot_a'"
   sha256sum stock-boot-a.img
   ```

2. Verify rollback before installing. From bootloader Fastboot, confirm the product and active slot with `fastboot getvar product` and `fastboot getvar current-slot`. With the user's explicit approval for the write, the verified stock restore procedure for slot A is:

   ```sh
   fastboot flash boot_a stock-boot-a.img
   fastboot reboot
   ```

   Confirm Android boots on slot A and the stock partition still matches the digest. A/B slot health and a temporary boot path remain unverified on this firmware.

3. From the repository checkout, package and inspect the namespace candidate using private paths.

   ```sh
   python3 scripts/package-namespace-boot.py <stock-boot-a.img> <namespace-build-output> <candidate.img>
   python3 scripts/inspect-boot-image.py <candidate.img>
   ```

4. After authorizing the candidate write, repeat the Fastboot product and slot checks and flash only `boot_a`.

   ```sh
   fastboot flash boot_a <candidate.img>
   fastboot reboot
   ```

   The tested phone booted without changing `init_boot`, `vendor_boot`, or `vbmeta`. Allow USB time to reappear. Verify `uname -r` reports the candidate's `5.15.180`, Android completed boot, root still works, and SELinux is enforcing. If the candidate fails, return to bootloader Fastboot and restore the verified stock image using step 2.
