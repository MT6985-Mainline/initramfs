# r360 display checkpoint — 2026-11-16

The complete MiCode `corot-t-oss` DRM v2, mi_disp, M12 panel and MML sources
are ported into the Linux 7.2.7 tree with their clock, PMIC, SCPSYS, EINT,
SCP, secure CMDQ, trusted-memory, DVFSRC, MMDVFS and MMQOS dependencies.
This is an experimental bring-up checkpoint; correct continuous display
output remains incomplete.

The tested panel is M12 `42_02_0a`, build ID `02`, at 1220 x 2712. The original
M12 command tables, DSC parameters and default PHY lane behavior are retained.
Stock IRIS operates in bypass, and the active test uses the primary DSI host.
The implementation queues a real first image after fresh panel enable while
keeping hardware external TE synchronization and real CMD_EOF completion.

## Confirmed r360 #13 hardware observations

The user photographed Linux console text over roughly 95% of the display,
with a fixed colored noise band at the bottom. The expected moving quadrant
test was not observed on the panel.

The uniquely tagged current cust log confirms:

- `7.2.7-corot-r360+ #13`, with `corot_test=r360`.
- Real first-frame epoch 4 completion at about 1.295 s.
- A fresh CPU DCS `0x0a` reply of `0x0c` before that image.
- After recovery, a fresh `0x0a` reply of `0x9c` at about 9.211 s,
  matching the running stock panel response.
- Actual TE_RDY and another first-frame epoch 11 completion.
- 23 complete CPU writes (frames 0 through 22) to `mediatekdrmfb`, each
  1220 x 2712, 32 bpp, pitch 4880, and 13,234,560 bytes.

CPU write counts alone do not establish that those later frames reached the
panel. The display freezes at early console content. The same current log
contains CMDQ waits/timeouts, DSI/OVL buffer underruns during recovery, and a
non-executable notifier callback Oops from `mtk_smi_larb_suspend` at about
18.387 s in the display idle-manager thread. PID 1 continues recording the log
and reaches its monotonic capture deadline, but automatic fastboot restoration
fails. These faults and bottom corruption are the next work items.

## Software and build validation

The actual first-frame command generators and native encoder/read/assign/
conditional-jump functions pass **33,643 scenarios / 13,443,505 assertions**
under ASan/UBSan, including all 480 instruction alignments and modeled eager
buffer relocation. This validates code generation, not physical scanout.

The four-bank EINT mapping matches all 254 positional stock entries and passes
256 scenarios / 9,221 assertions. Shared GPIO lookup lifetime validation passes
7 scenarios / 146 sanitizer assertions. All 173 MMQOS requests are audited;
14 destinations are corrected only where both the provider table and physical
SMI topology agree.

The complete r360 Image links, contains the exact compiled DTB and the genuine
MT6985 MML topology/initcall, and passes release/tag, payload and partition-size
checks. The kernel tree publishes the actual tested configuration.

| Artifact | SHA256 |
|---|---|
| Image | `8d984e34e5dccd14ed5b74ad494d5583c369b3545be3d6ebae5f6bb20f49bc14` |
| Embedded DTB | `5e7086ec28ecfe9312c50c537c635a357712345499d97883dfa9ac56881f5d2b` |
| Tested configuration | `696689e26f1161d3da01ae85b915bc1fa04d08aae849785ff692e68ba76e7855` |
| Legacy-LZ4 ramdisk | `f254c02bf94b1ba4628826e0539f687e53cbbc5ed6d6441d6d93c1e5ce206bc7` |

Original Android was restored only to the authorized device's slot a, and
both `boot_a` and `init_boot_a` hashes match the local pre-test backups.
The kernel source checkpoint is split by clock/power, pin/GPIO, PMIC, DVFS,
interconnect, SCP, secure memory/CMDQ, SLBC, MML, DRM, panel, mi_disp,
capture diagnostics and board integration. Original MiCode copyright notices
remain in the imported files; new progress commits are authored and signed off
as `mytiantian001`.

Source reference:
[MiCode corot-t-oss](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/cb2ab59a621b17aafa4a3f349c84d9f18adf7aaf).

## Kernel source commit series

The series advances the existing `7.2-mt6985-xiaomi-corot` branch from
`282b21b916bc93c8918f542d9bd45c89a96ed67f` to `92cfad231c05aef6d004cfdd1b6a35c0588178ba`.

| Category | Commit |
|---|---|
| clocks / power | [365208102b42](https://github.com/MT6985-Mainline/linux/commit/365208102b42d5358fd4c101ed66a12a2009dbb2) |
| pins / gpio | [4202fda6cbb2](https://github.com/MT6985-Mainline/linux/commit/4202fda6cbb287541a49c9581cff3f4c2bae3b17) |
| pmic | [bbae0a571152](https://github.com/MT6985-Mainline/linux/commit/bbae0a571152db96a7a11943679a2a3f9719b458) |
| dvfs | [9e887bfd53b8](https://github.com/MT6985-Mainline/linux/commit/9e887bfd53b885b7644a7f7895257e8f931243a5) |
| bandwidth | [299db608e4a0](https://github.com/MT6985-Mainline/linux/commit/299db608e4a09050eaee76424b56690eab6d3cf7) |
| scp | [cdaee8c085e7](https://github.com/MT6985-Mainline/linux/commit/cdaee8c085e7a0bef74099164f5748c987e4af2a) |
| secure | [839e9e8cfc1f](https://github.com/MT6985-Mainline/linux/commit/839e9e8cfc1fece37ad101ae02d6b3ac3bfac070) |
| slbc | [1ff2279b81e5](https://github.com/MT6985-Mainline/linux/commit/1ff2279b81e5f7912a19ad4524ca270d907c9720) |
| mml | [c64ec6294c7a](https://github.com/MT6985-Mainline/linux/commit/c64ec6294c7af267d488276b77f5ce55bdb27f83) |
| drm | [458545f4f664](https://github.com/MT6985-Mainline/linux/commit/458545f4f664501560de17e60961cd285f9ab284) |
| panel | [f9d74f75490d](https://github.com/MT6985-Mainline/linux/commit/f9d74f75490dd052e5ce753b93e9abee4209e645) |
| mi / disp | [70f11dc31ea2](https://github.com/MT6985-Mainline/linux/commit/70f11dc31ea2c602ace554351f0ebd4bc34f976f) |
| capture | [469a210dbe21](https://github.com/MT6985-Mainline/linux/commit/469a210dbe21f219a721c60c1d0d46fa00400586) |
| integration | [92cfad231c05](https://github.com/MT6985-Mainline/linux/commit/92cfad231c05aef6d004cfdd1b6a35c0588178ba) |
