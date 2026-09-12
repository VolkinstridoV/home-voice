"""Provision Wi-Fi on an Improv-BLE device (Home Assistant Voice PE) from the laptop.

Usage: improv_provision.py <ble-address> <ssid> <password> [--dry-run]
Mirrors what Home Assistant's improv_ble config flow does.
"""
import asyncio
import sys

from bleak import BleakScanner
from improv_ble_client import ImprovBLEClient, State, errors


async def main() -> int:
    address, ssid, password = sys.argv[1], sys.argv[2], sys.argv[3]
    dry_run = "--dry-run" in sys.argv

    print(f"scanning for {address} ...")
    device = await BleakScanner.find_device_by_address(address, timeout=15.0)
    if device is None:
        print("device not found")
        return 1
    print(f"found: {device.name} {device.address}")

    client = ImprovBLEClient(device)
    await client.ensure_connected()
    print("connected; can_identify =", client.can_identify)

    def on_state(state: State) -> None:
        print("state:", state)

    unsub = await client.subscribe_state_updates(on_state)
    try:
        need_auth = await client.need_authorization()
        print("need_authorization =", need_auth)
        waited = 0
        while need_auth and waited < 180:
            print(f"waiting for button press on the device ... {waited}s", flush=True)
            await asyncio.sleep(3)
            waited += 3
            need_auth = await client.need_authorization()
        if need_auth:
            print("no authorization within 180s, aborting")
            return 2
        print("authorized")
        if dry_run:
            print("dry run: not provisioning")
            return 0
        redirect = await client.provision(ssid, password, None)
        print("provisioned OK; redirect_url =", redirect)
        return 0
    except errors.ProvisioningFailed as err:
        print("provisioning failed:", err)
        return 3
    finally:
        unsub()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
