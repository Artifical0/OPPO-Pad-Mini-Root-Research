#!/system/bin/sh
MODDIR=${0%/*}
exec /system/bin/sh "$MODDIR/bin/ota.sh" status
