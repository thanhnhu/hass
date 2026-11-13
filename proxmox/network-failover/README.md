# Proxmox network failover (ethernet ⇄ wifi)

Host: `pve` – 192.168.2.100 (ethernet, `vmbr0`/`nic0`) · 192.168.2.101 (wifi, `wlp2s0`)

## Why

The old config put `nic0` + `wlp2s0` in `bond0` (active-backup). `bond-fail_over_mac active`
was never applied by ifupdown2 (`fail_over_mac = none`), so wifi associated to the AP with the
**same MAC as nic0**. The router saw one MAC on two ports → MAC flapping → traffic sent to the
wifi backup slave got dropped by the bond → flaky internet whenever wifi was on.

## What this does

- `vmbr0` bridges `nic0` only; wifi gets its own IP `.101`.
- `net-failover.service` checks `nic0` carrier every 5 s and swaps the route metrics:
  - ethernet up → vmbr0 metric 0, wifi 600
  - ethernet down → wifi metric 0, vmbr0 900
- Logs to journal only on switch: `journalctl -t net-failover`
- Starts on boot, restarts on crash, restores ethernet priority when stopped.

**Limit:** only the Proxmox host fails over. LXC/VMs on `vmbr0` lose network while ethernet is
down (wifi client mode only carries one MAC). While on wifi, reach the host at `192.168.2.101`.

## Install (run on pve, preferably from the console)

```sh
cp /etc/network/interfaces /etc/network/interfaces.bak-bond
install -m 755 net-failover.sh /usr/local/sbin/net-failover.sh
install -m 644 net-failover.service /etc/systemd/system/net-failover.service
install -m 644 99-multihome.conf /etc/sysctl.d/99-multihome.conf
install -m 644 interfaces /etc/network/interfaces
sysctl --system
ifreload -a
systemctl daemon-reload
systemctl enable --now net-failover.service
```

## Rollback

```sh
systemctl disable --now net-failover.service
cp /etc/network/interfaces.bak-bond /etc/network/interfaces
ifreload -a
```

## Check

```sh
ip route show default
ip rule | grep 101
journalctl -t net-failover
```
