#!/usr/bin/env bash

echo "======================================================"
echo "Starting Bluetooth audio configuration..."
echo "======================================================"

# 1. Create directory structures if they don't exist
echo "--> Creating local configuration directories..."
mkdir -p ~/.config/pipewire
mkdir -p ~/.config/wireplumber/wireplumber.conf.d/

# 2. Deploy Optimized PipeWire Pulse Buffers
echo "--> Configuring PipeWire-Pulse fragment sizes..."
cp /usr/share/pipewire/pipewire-pulse.conf ~/.config/pipewire/ 2>/dev/null || true

# We modify the local file to use the 1024/48000 stable buffer configuration
sed -i 's/#\?pulse.min.req.*/pulse.min.req      = 1024\/48000/' ~/.config/pipewire/pipewire-pulse.conf
sed -i 's/#\?pulse.min.frag.*/pulse.min.frag     = 1024\/48000/' ~/.config/pipewire/pipewire-pulse.conf
sed -i 's/#\?pulse.min.quantum.*/pulse.min.quantum  = 1024\/48000/' ~/.config/pipewire/pipewire-pulse.conf

# 3. Disable WirePlumber Seat Monitoring (Stops clock drifting)
echo "--> Disabling WirePlumber seat monitoring..."
cat << 'EOF' > ~/.config/wireplumber/wireplumber.conf.d/50-bluez-no-seat.conf
wireplumber.profiles = {
    main = {
        monitor.bluez.seat-monitoring = disabled
    }
}
EOF

# 4. Set High Priority Threading and Disable Buggy HW Volume
echo "--> Configuring WirePlumber Bluetooth priorities..."
cat << 'EOF' > ~/.config/wireplumber/wireplumber.conf.d/99-disable-rtkit.conf
monitor.bluez.properties = {
    bluez5.roles = [ a2dp_sink ]
    bluez5.hw-volume = false
}
EOF

# 5. Handle NetworkManager Power Management
echo "--> Disabling Wi-Fi power saving conflicts (Requires Sudo)..."
sudo mkdir -p /etc/NetworkManager/conf.d/
cat << 'EOF' | sudo tee /etc/NetworkManager/conf.d/default-wifi-powersave-on.conf > /dev/null
[main]
rc-manager=symlink

[connection]
wifi.powersave = 2
EOF

# 6. Apply BlueZ Dynamic Packet Adjustment Overrides
echo "--> Modifying main Bluetooth configurations (Requires Sudo)..."
if [ -f /etc/bluetooth/main.conf ]; then
    sudo sed -i 's/#\?MultiProfile.*/MultiProfile = multiple/' /etc/bluetooth/main.conf
    sudo sed -i 's/#\?FastConnectable.*/FastConnectable = true/' /etc/bluetooth/main.conf
fi

# 7. Purge Old Audio State Cache & Restart System Processes
echo "--> Flushing WirePlumber state and restarting audio services..."
rm -rf ~/.local/state/wireplumber

systemctl --user restart wireplumber pipewire pipewire-pulse
sudo systemctl restart bluetooth NetworkManager

echo "======================================================"
echo " Done! Turn your XM4s off and back on to test."
echo "======================================================"
