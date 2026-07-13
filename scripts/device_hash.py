import argparse
import hashlib
import platform
import subprocess
import time
import sys

def get_serial():
    os_name = platform.system()

    try:
        if os_name == "Linux":
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if "Serial" in line:
                            return line.split(":")[1].strip()
            except:
                pass

            cmd = "cat /sys/class/dmi/id/product_serial"
            return subprocess.check_output(cmd, shell=True).decode().strip()

        elif os_name == "Darwin":
            cmd = "system_profiler SPHardwareDataType | grep 'Serial Number (system)' | awk '{print $4}'"
            return subprocess.check_output(cmd, shell=True).decode().strip()

        else:
            raise Exception(f"Hệ điều hành {os_name} chưa được hỗ trợ.")

    except Exception as e:
        raise Exception(f"Lỗi truy xuất phần cứng: {e}")

def generate_secure_hash(node_id, serial, salt, timestamp):
    data = f"{node_id}{serial}{salt}{timestamp}".encode('utf-8')
    return hashlib.sha256(data).hexdigest()

def main():
    parser = argparse.ArgumentParser(description="Raspberry Pi Device Identity Generator")
    parser.add_argument('--node-id', required=True)
    parser.add_argument('--salt', required=True)

    args = parser.parse_args()
    
    try:
        serial = get_serial()
        current_timestamp = str(int(time.time()))
        device_hash = generate_secure_hash(args.node_id, serial, args.salt, current_timestamp)

        print(f"--- THÔNG TIN ĐỊNH DANH ---")
        print(f"Timestamp   : {current_timestamp}")
        print(f"Node ID     : {args.node_id}")
        print(f"Hardware SN : {serial}")
        print(f"Result Hash : {device_hash}")
        
    except Exception as e:
        print(f"LỖI NGHIÊM TRỌNG: {e}", file=sys.stderr)
        sys.exit(1) # Trả về mã lỗi để các hệ thống khác biết là thất bại

if __name__ == "__main__":
    main()