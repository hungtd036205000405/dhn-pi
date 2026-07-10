import platform
import subprocess
import sys

def get_serial_number():
    os_name = platform.system()remote
    
    try:
        if os_name == "Linux":
            # Kiểm tra xem có phải là Raspberry Pi không
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if "Serial" in line:
                            return line.split(":")[1].strip()
            except:
                pass
            
            # Đối với Linux thông thường
            cmd = "cat /sys/class/dmi/id/product_serial"
            return subprocess.check_output(cmd, shell=True).decode().strip()

        elif os_name == "Darwin":  # macOS
            cmd = "system_profiler SPHardwareDataType | grep 'Serial Number (system)' | awk '{print $4}'"
            return subprocess.check_output(cmd, shell=True).decode().strip()

        else:
            return f"Hệ điều hành {os_name} chưa được hỗ trợ."
            
    except Exception as e:
        return f"Lỗi khi lấy serial: {e}"

if __name__ == "__main__":
    serial = get_serial_number()
    print(f"Hệ điều hành: {platform.system()}")
    print(f"Serial Number: {serial}")