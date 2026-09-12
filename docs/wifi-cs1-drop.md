# The Wi-Fi that dropped exactly one kind of packet

Symptom: every `ssh server 'some command'` from the laptop hung after
authentication. Login succeeded, the command ran on the server, but not a
single byte came back. `ssh -tt` (with a pseudo-terminal) worked perfectly.

## What was actually happening

OpenSSH marks its packets with DSCP: interactive sessions get `EF`, bulk
(non-interactive) sessions get `CS1` — the "background" class. The server's
sshd had `IPQoS ef cs1`.

The laptop's Wi-Fi link dropped **100 % of packets marked CS1**, in both
directions, on both bands:

```
ping -Q 0x00  → 0 % loss
ping -Q 0xb8  → 0 % loss   (EF)
ping -Q 0x20  → 100 % loss (CS1)
```

`ss -tni` on the server showed the session socket retransmitting forever
(`backoff 12`, `cwnd 1`); on the laptop `bytes_received` froze at the last
pre-exec packet.

A phone on the same router passed CS1 fine on both bands, and the laptop over
an Ethernet cable passed it too. So: not the router, not sshd — the laptop's
MediaTek MT7925 Wi-Fi (`mt7925e`) with the WMM background access category.

## What fixed it (in that order, so the cause is not fully isolated)

1. Installed `wireless-regdb` — the kernel had been logging
   `failed to load regulatory.db` and ran in world regdom `00`.
2. Set `WIRELESS_REGDOM="US"`.
3. Reloaded the whole Wi-Fi driver stack (`mt7925e … cfg80211`). After that
   `wpa_supplicant` could not re-grab the interface ("couldn't grab this
   interface"); `systemctl restart wpa_supplicant` fixed it.

After this the laptop also saw the router's 5 GHz SSID it had been blind to,
and CS1 passed with 0 % loss. Whether the regulatory database or the driver
re-initialisation was the actual fix is unknown until the next reboot.

## Belt and braces on the server

`/etc/ssh/sshd_config.d/10-ipqos.conf`:

```
IPQoS ef cs0
```

sshd never marks anything CS1 again, so even if the Wi-Fi bug returns, SSH
does not hang.

## How to spot this in one minute next time

If SSH authenticates and then hangs: `ping -Q 0x20 <host>` in both
directions. If it drops while `-Q 0x00` passes, stop debugging sshd.
