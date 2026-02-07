import socket
import struct

UDP_IP = "0.0.0.0"
UDP_PORT = 20777

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

print("=" * 60)
print("F1 2018 PACKET ANALYZER")
print("=" * 60)
print("Listening on port 20777...")
print("Drive in F1 2018, then press Ctrl+C after a few seconds\n")

packets_captured = []
packet_count = 0

try:
    while packet_count < 100:  # Capture 100 packets
        data, addr = sock.recvfrom(2048)
        packets_captured.append(data)
        packet_count += 1
        
        if packet_count == 1:
            print(f"First packet received: {len(data)} bytes")

except KeyboardInterrupt:
    print(f"\nCaptured {packet_count} packets")

finally:
    sock.close()

# Analyze the first packet
if packets_captured:
    first_packet = packets_captured[0]
    
    print("\n" + "=" * 60)
    print("PACKET ANALYSIS")
    print("=" * 60)
    print(f"Packet size: {len(first_packet)} bytes")
    
    # Try to find lap time (should be a float near current time)
    print("\nSearching for lap time patterns...")
    
    for offset in range(0, len(first_packet) - 4, 4):
        try:
            value = struct.unpack('<f', first_packet[offset:offset+4])[0]
            
            # Lap times are typically between 60-200 seconds
            if 0 < value < 200:
                print(f"  Offset {offset:3d}: {value:8.3f}s (possible lap time)")
        except:
            pass
    
    # Try to find speed (should be 0-400)
    print("\nSearching for speed patterns...")
    
    for offset in range(0, len(first_packet) - 2, 2):
        try:
            value = struct.unpack('<H', first_packet[offset:offset+2])[0]
            
            # Speed typically 0-400 km/h
            if 0 < value < 400:
                print(f"  Offset {offset:3d}: {value:3d} km/h (possible speed)")
        except:
            pass
    
    # Dump first 100 bytes in hex for manual inspection
    print("\nFirst 100 bytes (hex):")
    for i in range(0, min(100, len(first_packet)), 16):
        hex_str = ' '.join(f'{b:02x}' for b in first_packet[i:i+16])
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in first_packet[i:i+16])
        print(f"  {i:04d}: {hex_str:<48s} | {ascii_str}")
    
    print("\n" + "=" * 60)
    print("Save this output and share it")
    print("=" * 60)
# ```

# ---

# ## 🎯 What to do:

# 1. **Make sure F1 2018 is set to "2018" format** (NOT Legacy)
# 2. Run this analyzer:
# ```
#    python scripts/packet_analyzer.py
