import argparse
import hashlib
import time
import sys

def get_serial():
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Serial'):
                    return line.split(':')[1].strip()
        # Nếu đã duyệt hết file mà không thấy dòng Serial
        raise Exception("Không tìm thấy thông số Serial trong hệ thống!")
    except FileNotFoundError:
        raise Exception("Hệ thống không phải Raspberry Pi (không tìm thấy /proc/cpuinfo)")
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