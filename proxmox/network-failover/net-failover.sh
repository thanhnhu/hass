#!/bin/sh
# net-failover: host-level failover nic0 (ethernet, via vmbr0) <-> wlp2s0 (wifi)
#
# - Kiem tra carrier cua nic0 moi INTERVAL giay (doc file ao trong /sys, khong ghi o cung).
# - Ethernet song  -> route qua vmbr0 metric 0, wifi metric 600.
# - Ethernet chet  -> route qua wifi metric 0, vmbr0 metric 900.
# - Chi ghi log (logger) khi doi trang thai.
# - Neu route bi thay doi tu ben ngoai (vd: ifreload -a) thi tu ap dung lai (khong log).
#
# Luu y: chi host Proxmox duoc failover. LXC/VM tren vmbr0 KHONG di qua wifi duoc
# (wifi client mode chi cho 1 MAC).
#
# Dung: net-failover.sh          -> chay vong lap giam sat
#       net-failover.sh restore  -> tra route ve mac dinh (ethernet uu tien) roi thoat

ETH=nic0
BR=vmbr0
WIFI=wlp2s0
GW=192.168.2.1
NET=192.168.2.0/24
BR_IP=192.168.2.100
WIFI_IP=192.168.2.101
INTERVAL=5

# set_prio <dev> <src-ip> <metric>: dat metric cho route subnet LAN + default route cua dev
set_prio() {
    while ip -4 route del "$NET" dev "$1" table main 2>/dev/null; do :; done
    while ip -4 route del default dev "$1" table main 2>/dev/null; do :; done
    ip -4 route add "$NET" dev "$1" proto kernel scope link src "$2" metric "$3" 2>/dev/null
    ip -4 route add default via "$GW" dev "$1" metric "$3" 2>/dev/null
}

use_eth() {
    set_prio "$BR" "$BR_IP" 0
    set_prio "$WIFI" "$WIFI_IP" 600
}

use_wifi() {
    set_prio "$WIFI" "$WIFI_IP" 0
    set_prio "$BR" "$BR_IP" 900
}

# dev cua default route dang duoc uu tien (metric nho nhat)
active_dev() {
    ip -4 route show default table main | awk 'NR==1{for(i=1;i<NF;i++) if($i=="dev"){print $(i+1); exit}}'
}

if [ "$1" = "restore" ]; then
    use_eth
    exit 0
fi

mode=""
while :; do
    c=0
    read c < "/sys/class/net/$ETH/carrier" 2>/dev/null || c=0
    if [ "$c" = "1" ]; then want=eth; dev=$BR; else want=wifi; dev=$WIFI; fi

    if [ "$want" != "$mode" ] || [ "$(active_dev)" != "$dev" ]; then
        if [ "$want" = eth ]; then use_eth; else use_wifi; fi
        if [ "$want" != "$mode" ]; then
            logger -t net-failover "switched to $want (via $dev)"
            mode=$want
        fi
    fi
    sleep "$INTERVAL"
done
