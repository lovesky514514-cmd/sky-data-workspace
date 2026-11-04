import ctypes
import os
import time


def watch(pid, shutdown):
    """只监测明确传入的桌面父进程，父进程退出后停止本运行时。"""
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.WaitForSingleObject.restype = ctypes.c_ulong
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if handle:
            try:
                while kernel.WaitForSingleObject(handle, 1000) == 0x00000102:
                    pass
            finally:
                kernel.CloseHandle(handle)
        shutdown()
    else:
        while True:
            try:
                os.kill(pid, 0)
            except OSError:
                shutdown()
                return
            time.sleep(1)
