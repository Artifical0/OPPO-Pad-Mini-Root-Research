SKIPMOUNT=true
[ "$KSU" = true ] || abort "请使用 KernelSU 管理器安装。"
[ "$(getprop ro.product.model)" = OPD2515 ] || abort "仅适用于 OPD2515。"
[ "$(getprop ro.boot.flash.locked)" = 0 ] || abort "需要真实 BL 已解锁的 Normal Boot。"
case "$(uname -r)" in 6.12.*-android16-6-*) ;; *) abort "当前内核不在本版支持范围。" ;; esac
[ -x /data/adb/ksu/bin/busybox ] || abort "缺少 KernelSU BusyBox。"
set_perm_recursive "$MODPATH/bin" 0 0 0755 0755
set_perm "$MODPATH/action.sh" 0 0 0755
ui_print "安装只放置工具，不刷写分区，也不改变启动菜单。"
ui_print "初次安装完成后，打开模块 WebUI 查看使用步骤。"
ui_print "每次 OTA 都需要先检查目标完整固件；不会自动保留未知新版。"
