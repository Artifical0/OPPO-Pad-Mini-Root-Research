SKIPMOUNT=true
[ "$KSU" = true ] || abort "请使用 KernelSU 管理器安装。"
[ "$(getprop ro.product.model)" = OPD2515 ] || abort "仅适用于 OPD2515。"
case "$(uname -r)" in 6.12.*-android16-6-*) ;; *) abort "当前内核不在支持范围。" ;; esac
[ -x /data/adb/ksu/bin/busybox ] || abort "缺少 KernelSU BusyBox。"
set_perm_recursive "$MODPATH/bin" 0 0 0755 0755
set_perm "$MODPATH/action.sh" 0 0 0755
ui_print "0.2.0-rc1 研究预览版：尚未完成真机安装和 OTA 验证。"
ui_print "安装仅放置工具；不写启动分区，不自动保留或重启。"
ui_print "打开 WebUI，按每次 OTA 的备份、电脑审查和保留步骤操作。"
