# Verizon Boot Debranding on Moto G Power 2026 (`vegas26`)

This document provides automated and manual instructions to replicate the Verizon boot debranding modification across any rooted Motorola Moto G Power 2026 (`vegas26`) device sharing the `XT2617V` hardware SKU.

The modification is entirely systemless and reversible. It removes the bright red Verizon splash screen and looping dots while preserving the original Motorola Batwing logo, the authentic "Hello Moto" audio/video sequence, and the official Motorola looping boot animation.

---

## Device Compatibility & Prerequisites

Before attempting replication, verify that the target phone matches the supported hardware SKU, operating system, and root configuration:

| Parameter | Required Specification | Verification Command |
| :--- | :--- | :--- |
| **Device Codename** | `vegas` or `vegas26` | `adb shell getprop ro.product.device` |
| **Hardware SKU** | `XT2617V` | `adb shell getprop ro.boot.hardware.sku` |
| **OS Version** | Android 16 | `adb shell getprop ro.build.version.release` |
| **Active Carrier** | `tracfone`, `vzw`, or `vzwpre` | `adb shell getprop ro.carrier` |
| **Root Solution** | Magisk (v26+ / v31+), KernelSU, or APatch | `adb shell su --mount-master -c 'id'` |
| **Bootloader** | Unlocked | `adb shell getprop ro.boot.vbmeta.device_state` |

> [!IMPORTANT]
> The `XT2617V` hardware SKU is the carrier-customized variant for Verizon and its MVNOs (such as TracFone/Straight Talk on the Verizon network). Do not install this configuration on non-`vegas26` Motorola platforms.

---

## Automated Replication (Recommended)

The repository provides an automated replication and verification tool: `scripts/debrand-verizon-boot.py`.

### 1. Verify Target Device

Ensure the target phone is connected over USB and authorized in ADB:

```sh
python3 scripts/debrand-verizon-boot.py --verify
```

Expected output:
```text
[-] Checking connected device...
    Device:   vegas26
    SKU:      XT2617V
    Release:  Android 16
    Carrier:  tracfone
    Root:     Verified (uid=0(root) gid=0(root) groups=0(root) context=u:r:magisk:s0)
[-] Auditing debranding status on device...
    Module installed: NO
    ...
```

### 2. Deploy Debranding Module and Reboot

Run the deployment script with `--reboot` to automatically extract the device's stock unbranded Motorola boot animation, construct the flashable systemless module, install it via the root manager, and restart the device:

```sh
python3 scripts/debrand-verizon-boot.py --reboot
```

### 3. Verify Active Debranding After Reboot

Once the device finishes rebooting, verify that all carrier boot animation paths reflect the clean Motorola digest:

```sh
python3 scripts/debrand-verizon-boot.py --verify
```

Expected output:
```text
[-] Checking connected device...
    Device:   vegas26
    SKU:      XT2617V
    Release:  Android 16
    Carrier:  tracfone
    Root:     Verified (uid=0(root) gid=0(root) groups=0(root) context=u:r:magisk:s0)
[-] Auditing debranding status on device...
    Module installed: YES
    tracfone   ac78f4801341a8cbd4a1a6a2cb90df6781ece1a99427181b53330195e74f9f46  /product/carrier/tracfone/media/bootanimation.zip
    vzw        ac78f4801341a8cbd4a1a6a2cb90df6781ece1a99427181b53330195e74f9f46  /product/carrier/vzw/media/bootanimation.zip
    vzwpre     ac78f4801341a8cbd4a1a6a2cb90df6781ece1a99427181b53330195e74f9f46  /product/carrier/vzwpre/media/bootanimation.zip
```

---

## Manual Step-by-Step Replication

If you prefer to perform each step manually or inspect the archive contents directly, follow this procedure:

### Step 1: Back Up Carrier Animation

Before applying any changes, pull and back up the active carrier animation from the phone:

```sh
mkdir -p backups
adb pull /product/carrier/tracfone/media/bootanimation.zip backups/tracfone_bootanimation.zip
sha256sum backups/tracfone_bootanimation.zip
```

### Step 2: Extract Clean Motorola Assets

Every `vegas26` firmware build includes the unbranded stock Motorola boot animation in the read-only `/product` partition:

```sh
adb pull /product/media/bootanimation.zip backups/product_bootanimation.zip
```

This archive contains:
- `01_moto.mp4`: Motorola "Hello Moto" animation with sound (1080x2388, 30 fps, 6.06s).
- `02_loop.mp4`: Motorola batwing dynamic loop (1080x2388, 30 fps, 3.46s).
- `sol.png`: Motorola static overlay.
- `videodesc.txt`: Video playback sequence (`1 0` -> play `01_moto.mp4` once; `0 1` -> loop `02_loop.mp4` indefinitely).

### Step 3: Build the Root Module Hierarchy

Create a local staging directory for the module:

```sh
mkdir -p module/system/product/carrier/tracfone/media
mkdir -p module/system/product/carrier/vzw/media
mkdir -p module/system/product/carrier/vzwpre/media
mkdir -p module/META-INF/com/google/android
```

1. **Write `module/module.prop`**:
   ```ini
   id=vegas26_verizon_debranding
   name=Motorola Verizon Boot Debranding
   version=1.0.0
   versionCode=1
   author=Local
   description=Removes Verizon boot branding while preserving the original Motorola Hello Moto animation.
   ```

2. **Copy the Clean Boot Animation**:
   Copy the unbranded `product_bootanimation.zip` as `bootanimation.zip` into each carrier directory:
   ```sh
   cp backups/product_bootanimation.zip module/system/product/carrier/tracfone/media/bootanimation.zip
   cp backups/product_bootanimation.zip module/system/product/carrier/vzw/media/bootanimation.zip
   cp backups/product_bootanimation.zip module/system/product/carrier/vzwpre/media/bootanimation.zip
   ```

3. **Write `module/post-fs-data.sh`**:
   ```sh
   #!/system/bin/sh
   MODDIR=${0%/*}
   LOGFILE="/data/local/tmp/verizon_debranding.log"

   echo "=== Verizon Debranding post-fs-data $(date) ===" > "$LOGFILE"
   echo "MODDIR: $MODDIR" >> "$LOGFILE"

   for carrier_name in tracfone vzw vzwpre; do
       target="/product/carrier/$carrier_name/media/bootanimation.zip"
       source="$MODDIR/system/product/carrier/$carrier_name/media/bootanimation.zip"
       if [ -f "$target" ] && [ -f "$source" ]; then
           if grep -q "$target" /proc/mounts; then
               echo "$target already mounted by magic mount" >> "$LOGFILE"
           else
               mount -o bind "$source" "$target" 2>> "$LOGFILE" && \
                   echo "Explicitly bind-mounted $source -> $target" >> "$LOGFILE" || \
                   echo "Failed to bind-mount $target" >> "$LOGFILE"
           fi
       fi
   done
   ```
   Ensure execution permissions:
   ```sh
   chmod +x module/post-fs-data.sh
   ```

4. **Write `module/META-INF/com/google/android/update-binary`**:
   ```sh
   #!/sbin/sh
   umask 022
   OUTFD=$2
   ZIPFILE=$3
   if [ -f /data/adb/magisk/util_functions.sh ]; then
     . /data/adb/magisk/util_functions.sh
   elif [ -f /data/adb/ksu/bin/util_functions.sh ]; then
     . /data/adb/ksu/bin/util_functions.sh
   elif [ -f /data/adb/ap/bin/util_functions.sh ]; then
     . /data/adb/ap/bin/util_functions.sh
   fi
   install_module
   exit 0
   ```
   Ensure execution permissions:
   ```sh
   chmod +x module/META-INF/com/google/android/update-binary
   echo "#MAGISK" > module/META-INF/com/google/android/updater-script
   ```

### Step 4: Package Flashable Module ZIP

> [!WARNING]
> Android's `libbootanimation.so` requires entries inside `bootanimation.zip` to be stored uncompressed (`ZIP_STORED`, compression method 0).

Package the module using Python to guarantee uncompressed storage:

```sh
python3 -c "
import zipfile, os

base_dir = 'module'
out_zip = 'vegas26_verizon_debranding.zip'

with zipfile.ZipFile(out_zip, 'w', compression=zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, base_dir)
            if f == 'bootanimation.zip':
                with open(full_path, 'rb') as bf:
                    zinfo = zipfile.ZipInfo(rel_path)
                    zinfo.compress_type = zipfile.ZIP_STORED
                    z.writestr(zinfo, bf.read())
            else:
                z.write(full_path, arcname=rel_path)
"
```

### Step 5: Install and Reboot

1. Push the module to the device:
   ```sh
   adb push vegas26_verizon_debranding.zip /data/local/tmp/
   ```

2. Install using Magisk:
   ```sh
   adb shell su --mount-master -c 'magisk --install-module /data/local/tmp/vegas26_verizon_debranding.zip'
   adb shell su --mount-master -c 'rm -f /data/local/tmp/vegas26_verizon_debranding.zip'
   ```

3. Reboot the phone:
   ```sh
   adb reboot
   ```

---

## Technical Architecture

### How Motorola Selects Boot Animations
1. At early boot, `/system/bin/init.mmi.carrier.sh` checks the device carrier properties (`ro.carrier`). On the `XT2617V` SKU, this sets:
   ```properties
   persist.carrier.media.dir = /product/carrier/tracfone/media
   ```
2. When SurfaceFlinger starts `/system/bin/bootanimation`, Android's `libbootanimation.so` queries `persist.carrier.media.dir`.
3. If `%s/bootanimation.zip` exists in that directory, `bootanimation` loads that file instead of the default `/product/media/bootanimation.zip`.
4. Overriding all three carrier targets (`tracfone`, `vzw`, `vzwpre`) guarantees that even if a SIM card or APN changes the active channel ID, the unbranded Motorola boot animation is always loaded.

### Static Logo Partition (`logo_a` / `logo_b`)
- The static initial splash screen (the "hello moto Powered by Android" image displayed before the kernel initializes) resides in `/dev/block/by-name/logo_a`.
- The logo partition on `vegas26` uses a standard MediaTek container (`0x58881688`) and contains **no Verizon branding**. All Verizon branding exists exclusively in the MP4 video boot animation files. Flashing or modifying the logo partition is neither required nor recommended.

---

## Rollback & Uninstallation

To restore the factory carrier animation at any time:

### Option 1: Automated Script Uninstallation
```sh
python3 scripts/debrand-verizon-boot.py --uninstall --reboot
```

### Option 2: Fast Disable via ADB
```sh
adb shell su --mount-master -c 'touch /data/adb/modules/vegas26_verizon_debranding/disable'
adb reboot
```

### Option 3: Complete Removal via ADB
```sh
adb shell su --mount-master -c 'rm -rf /data/adb/modules/vegas26_verizon_debranding'
adb reboot
```

### Option 4: Hardware Safe Mode Recovery
If any issues occur during boot:
1. Power off the phone.
2. Hold `Power` until the Motorola splash screen appears, then immediately press and hold `Volume Down` until the system finishes booting.
3. Magisk will detect Safe Mode and disable all modules automatically.
