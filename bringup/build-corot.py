#!/usr/bin/env python3
"""Build the corot kernel in a separate output directory."""
import argparse
import os
import re
from pathlib import Path
import shutil
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--name", default="r341")
parser.add_argument("--source", type=Path, default=Path("linux"))
parser.add_argument("--release", default=None)
parser.add_argument("--target", choices=("all", "drm", "panel", "scp", "power", "secure", "providers"), default="all")
parser.add_argument("--jobs", type=int, default=8)
args = parser.parse_args()
if not args.name.replace("-", "").isalnum():
    raise SystemExit("Build name must be alphanumeric")
root = Path(__file__).resolve().parent.parent
source = root / args.source
out = root / "out" / args.name
out.mkdir(parents=True, exist_ok=True)
if not (out / ".config").exists():
    shutil.copy2(source / ".config", out / ".config")
subprocess.run([str(source / "scripts/config"), "--file", str(out / ".config"), "--set-str", "LOCALVERSION", "-corot-" + (args.release or args.name), "--disable", "LOCALVERSION_AUTO"], check=True)
native_required = ()
if source.name == "linux-native":
    native_required = (
        "COMMON_CLK_MT6985_CAM", "COMMON_CLK_MT6985_IMG",
        "COMMON_CLK_MT6985_VCODEC", "COMMON_CLK_MT6985_CCU",
        "MTK_MML", "MTK_MML_MT6985",
        "DRM_MEDIATEK_V2", "DRM_PANEL_COROT_M12", "MI_DISP", "MI_DISP_ESD_CHECK",
        "MTK_CMDQ_MBOX_EXT", "MTK_CMDQ_SECURE", "SPMI_MTK_COROT",
        "MFD_MTK_SPMI_PMIC", "REGULATOR_MT6363_COROT", "REGULATOR_MT6373", "MTK_IOMMU_MT6985",
        "GPIO_SHARED", "GPIO_SHARED_PROXY", "RESET_GPIO",
        "MTK_SCPSYS_MT6985", "MTK_MBOX", "MTK_IPI", "RPMSG_MTK_MBOX",
        "MTK_TINYSYS_SCP_SUPPORT", "MTK_GENIEZONE", "MTK_GZ_MAIN",
        "MTK_GZ_KREE", "MTK_GZ_TZ_SYSTEM", "MTK_GZ_VIRTIO", "MTK_GZ_VIRTIO_IPC",
        "MTK_GZ_IRQ", "MTK_PROT_MEM_SUPPORT", "MTK_SECURE_MEM_SUPPORT",
        "MTK_WFD_SMEM_SUPPORT", "MTK_TRUSTED_MEMORY_SUBSYSTEM", "DMABUF_HEAPS_MTK_SECURE",
        "MTK_DVFSRC", "REGULATOR_MTK_DVFSRC", "MTK_MMDVFS", "INTERCONNECT_MTK",
        "INTERCONNECT_MTK_EMI", "INTERCONNECT_MTK_MMQOS_MT6985", "MTK_DRAMC",
        "SYSCON_REBOOT_MODE", "MEDIATEK_WATCHDOG", "WATCHDOG_SYSFS",
    )
    options = ["--disable", "DRM_PANEL_M12_MIN", "--disable", "XAGA_MARKER_WRITER", "--disable", "REGULATOR_MT6363"]
    options.extend(("--set-val", "WATCHDOG_OPEN_TIMEOUT", "30"))
    for symbol in native_required:
        options.extend(("--enable", symbol))
    subprocess.run([str(source / "scripts/config"), "--file", str(out / ".config")] + options, check=True)
temporary = out / 'build-scratch'
temporary.mkdir(parents=True, exist_ok=True)
os.environ['TMPDIR'] = str(temporary.resolve())
base = ["make", "-C", str(source), "O=" + str(out), "ARCH=arm64", "LLVM=1", "LLVM_IAS=1"]
log = out / ("build.log" if args.target == "all" else args.target + "-build.log")
# This repository tracks .config; Kbuild refuses O= while it is in source.
# Preserve it byte-for-byte during the build and restore it on every exit.
original = source / ".config"
held = source / ".config.corot-build-held"
if held.exists():
    raise SystemExit("A build already holds source .config; inspect that process first")
original.rename(held)
try:
    with log.open("a") as f:
        f.write("\n=== " + (args.release or args.name) + " " + args.target + " build " + time.strftime("%Y-%m-%d %H:%M:%S") + " ===\n")
        f.flush()
        subprocess.run(base + ["olddefconfig"], stdout=f, stderr=subprocess.STDOUT, check=True)
        configured = set((out / ".config").read_text().splitlines())
        missing = [symbol for symbol in native_required if "CONFIG_" + symbol + "=y" not in configured]
        if missing:
            raise SystemExit("Native display providers were not enabled: " + ", ".join(missing))
        print("Configuration ready; building " + str(out), flush=True)
        if args.target == "all":
            subprocess.run(base + ["mediatek/mt6985-xiaomi-corot.dtb"], stdout=f, stderr=subprocess.STDOUT, check=True)
            subprocess.run(base + ["-j" + str(args.jobs), "Image"], stdout=f, stderr=subprocess.STDOUT, check=True)
            if source.name == "linux-native":
                symbols = (out / "System.map").read_text()
                if not re.search(r" [dDrR] tp_ops_mt6985(?:$|[.])", symbols, re.MULTILINE):
                    raise SystemExit("The real MT6985 MML topology was not linked")
                if not any("initcall" in line and "kmod_mtk_mml_mt6985" in line
                           for line in symbols.splitlines()):
                    raise SystemExit("MT6985 MML topology registration is absent from initcalls")

        else:
            subprocess.run(base + ["-j" + str(args.jobs), "prepare"], stdout=f, stderr=subprocess.STDOUT, check=True)
            if args.target in ("drm", "panel"):
                if args.target == "drm":
                    subprocess.run(base + ["-j" + str(args.jobs), "drivers/gpu/drm/mediatek/mediatek_v2/"], stdout=f, stderr=subprocess.STDOUT, check=True)
                    subprocess.run(base + ["-j" + str(args.jobs), "drivers/gpu/drm/mediatek/mml/"], stdout=f, stderr=subprocess.STDOUT, check=True)
                targets = ["drivers/gpu/drm/panel/panel-m12-42-02-0a-dsc-cmd.o", "drivers/gpu/drm/panel/panel-m12-36-02-0b-dsc-cmd.o"]
            elif args.target == "scp":
                targets = ["drivers/misc/mediatek/scp/rv/", "drivers/soc/mediatek/mtk-mbox.o", "drivers/soc/mediatek/mtk_tinysys_ipi.o", "drivers/rpmsg/mtk_rpmsg_mbox.o"]
            elif args.target == "power":
                targets = ["drivers/soc/mediatek/mtk-dvfsrc.o", "drivers/soc/mediatek/mtk-dvfsrc-start.o", "drivers/soc/mediatek/mtk-mmdvfs.o", "drivers/regulator/mtk-dvfsrc-regulator.o", "drivers/interconnect/mediatek/", "drivers/misc/mediatek/mtk-interconnect/", "drivers/memory/mediatek/dramc.o"]
            elif args.target == "providers":
                targets = [
                    "drivers/clk/mediatek/clk-mtk.o", "drivers/clk/mediatek/clk-pll.o",
                    "drivers/clk/mediatek/clk-gate.o", "drivers/clk/mediatek/clk-mux.o",
                    "drivers/clk/mediatek/clk-mt6985.o",
                    "drivers/clk/mediatek/clk-mt6985-cam.o", "drivers/clk/mediatek/clk-mt6985-img.o",
                    "drivers/clk/mediatek/clk-mt6985-vcodec.o", "drivers/clk/mediatek/clk-mt6985-ccu.o",
                    "drivers/soc/mediatek/mtk-scpsys.o", "drivers/soc/mediatek/mtk-scpsys-mt6985.o",
                    "drivers/soc/mediatek/mtk-scpsys-mt6895.o",
                    "drivers/pinctrl/mediatek/mtk-eint.o", "drivers/pinctrl/mediatek/pinctrl-mtk-common-v2.o",
                    "drivers/pinctrl/mediatek/pinctrl-paris.o", "drivers/pinctrl/mediatek/pinctrl-mt6985.o",
                    "drivers/pinctrl/mediatek/pinctrl-mt6895.o",
                    "drivers/spmi/spmi-mtk-corot-core.o", "drivers/mfd/mtk-spmi-pmic.o",
                    "drivers/regulator/mt6363-corot-regulator.o",
                    "drivers/gpio/gpiolib-shared.o", "drivers/gpio/gpio-shared-proxy.o",
                    "drivers/reset/reset-gpio.o", "drivers/usb/mtu3/mtu3_plat.o",
                ]
            else:
                targets = ["drivers/misc/mediatek/geniezone/", "drivers/misc/mediatek/trusted_mem/", "drivers/misc/mediatek/cmdq/mailbox/", "drivers/dma-buf/heaps/mtk_sec_heap.o"]
            subprocess.run(base + ["-j" + str(args.jobs)] + targets, stdout=f, stderr=subprocess.STDOUT, check=True)
finally:
    held.rename(original)
print("Build complete: " + (str(out / "arch/arm64/boot/Image") if args.target == "all" else args.target + " objects verified in " + str(out)))
