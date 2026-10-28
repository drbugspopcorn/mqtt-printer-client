'''
    Host health for the fleet page.  Stdlib only (no psutil) so it installs cleanly on old Pis.
    Everything here degrades to None rather than raising - a missing sensor shouldn't kill the heartbeat.
    Linux reads /proc and /sys; Windows goes through ctypes and the registry.
'''
import ctypes
import glob
import os
import platform
import shutil
import socket
import subprocess
import sys
import time

WINDOWS = sys.platform == 'win32'


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, ValueError):
        return None


def _windows_registry(path, name):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return str(winreg.QueryValueEx(key, name)[0]).strip()
    except OSError:
        return None


def _os_name():
    if WINDOWS:
        product = _windows_registry(r'SOFTWARE\Microsoft\Windows NT\CurrentVersion', 'ProductName')
        build = _windows_registry(r'SOFTWARE\Microsoft\Windows NT\CurrentVersion', 'CurrentBuild')
        # ProductName still says "Windows 10" on Windows 11 - the build number is the tell
        if product and build and build.isdigit() and int(build) >= 22000:
            product = product.replace('Windows 10', 'Windows 11')
        display = _windows_registry(r'SOFTWARE\Microsoft\Windows NT\CurrentVersion', 'DisplayVersion')
        return ' '.join(p for p in (product, display) if p) or f"Windows {platform.release()}"
    for line in (_read('/etc/os-release') or '').splitlines():
        if line.startswith('PRETTY_NAME='):
            return line.split('=', 1)[1].strip('"')
    return f"{platform.system()} {platform.release()}"


def _model():
    if WINDOWS:
        maker = _windows_registry(r'HARDWARE\DESCRIPTION\System\BIOS', 'SystemManufacturer')
        model = _windows_registry(r'HARDWARE\DESCRIPTION\System\BIOS', 'SystemProductName')
        return ' '.join(p for p in (maker, model) if p) or None
    model = _read('/proc/device-tree/model') or _read('/sys/class/dmi/id/product_name')
    return model.replace('\x00', '') if model else None


def local_ip(target_host='8.8.8.8'):
    ''' the address we'd use to reach the broker - no packets are actually sent for a UDP connect '''
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target_host, 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def host_info(broker_host=None):
    return {
        'hostname': socket.gethostname(),
        'os': _os_name(),
        'kernel': platform.release(),
        'arch': platform.machine(),
        'model': _model(),
        'python': platform.python_version(),
        'ip': local_ip(broker_host or '8.8.8.8'),
    }


def uptime_seconds():
    if WINDOWS:
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_uint64
        return ctypes.windll.kernel32.GetTickCount64() / 1000.0
    raw = _read('/proc/uptime')
    return float(raw.split()[0]) if raw else None


def cpu_temp():
    ''' hottest thermal zone in degrees C '''
    temps = []
    for zone in glob.glob('/sys/class/thermal/thermal_zone*/temp'):
        raw = _read(zone)
        if raw and raw.lstrip('-').isdigit():
            temps.append(int(raw) / 1000.0)
    return round(max(temps), 1) if temps else None


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]


def _windows_memory():
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    total, available = status.ullTotalPhys, status.ullAvailPhys
    return {
        'total': total,
        'available': available,
        'percent': round(100.0 * (total - available) / total, 1) if total else None,
        'swap_used': max(0, (status.ullTotalPageFile - status.ullAvailPageFile) - (total - available)),
    }


def memory():
    if WINDOWS:
        return _windows_memory()
    info = {}
    for line in (_read('/proc/meminfo') or '').splitlines():
        key, _, rest = line.partition(':')
        if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            info[key] = int(rest.split()[0]) * 1024
    if 'MemTotal' not in info:
        return None
    total, available = info['MemTotal'], info.get('MemAvailable', 0)
    return {
        'total': total,
        'available': available,
        'percent': round(100.0 * (total - available) / total, 1) if total else None,
        'swap_used': info.get('SwapTotal', 0) - info.get('SwapFree', 0),
    }


ROOT = (os.environ.get('SystemDrive', 'C:') + '\\') if WINDOWS else '/'


def disk(path=ROOT):
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {
        'path': path,
        'total': usage.total,
        'free': usage.free,
        'percent': round(100.0 * usage.used / usage.total, 1) if usage.total else None,
    }


# https://www.raspberrypi.com/documentation/computers/os.html#get_throttled
THROTTLE_FLAGS = {
    0: 'under_voltage',
    1: 'freq_capped',
    2: 'throttled',
    3: 'soft_temp_limit',
    16: 'under_voltage_occurred',
    17: 'freq_capped_occurred',
    18: 'throttled_occurred',
    19: 'soft_temp_limit_occurred',
}


def pi_throttled():
    ''' Raspberry Pi only.  Under-voltage is the #1 cause of flaky Pis, so it's worth surfacing. '''
    if not shutil.which('vcgencmd'):
        return None
    try:
        out = subprocess.run(['vcgencmd', 'get_throttled'], capture_output=True, text=True, timeout=5).stdout
        value = int(out.strip().split('=')[1], 16)
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return None
    return {'raw': hex(value), 'flags': [name for bit, name in THROTTLE_FLAGS.items() if value & (1 << bit)]}


def metrics(document_location=None):
    uptime = uptime_seconds()
    load = os.getloadavg() if hasattr(os, 'getloadavg') else None
    disks = [disk(ROOT)]
    if document_location:
        doc_disk = disk(os.path.abspath(document_location))
        if doc_disk and disks[0] and doc_disk['total'] != disks[0]['total']:
            disks.append(doc_disk)
    return {
        'uptime': uptime,
        'boot_time': time.time() - uptime if uptime is not None else None,
        'cpu_temp': cpu_temp(),
        'cpu_count': os.cpu_count(),
        'load': [round(l, 2) for l in load] if load else None,
        'memory': memory(),
        'disks': [d for d in disks if d],
        'throttled': pi_throttled(),
    }


if __name__ == '__main__':
    import json
    json.dump({'host': host_info(), 'metrics': metrics()}, sys.stdout, indent=2)
