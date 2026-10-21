"""No-capability Windows AppContainer + kill-on-close resource-limited job.
Only an explicitly granted worker EXE and private AppContainer temp are readable.
The original file crosses anonymous pipes; no account files or network capability.
"""
import ctypes as C
from ctypes import wintypes as W
from functools import lru_cache
import os
from pathlib import Path
import subprocess
import threading

class SecurityAttributes(C.Structure):
    _fields_=[('nLength',W.DWORD),('lpSecurityDescriptor',C.c_void_p),('bInheritHandle',W.BOOL)]
class Startup(C.Structure):
    _fields_=[('cb',W.DWORD),('lpReserved',W.LPWSTR),('lpDesktop',W.LPWSTR),('lpTitle',W.LPWSTR),
              ('dwX',W.DWORD),('dwY',W.DWORD),('dwXSize',W.DWORD),('dwYSize',W.DWORD),('dwXCountChars',W.DWORD),
              ('dwYCountChars',W.DWORD),('dwFillAttribute',W.DWORD),('dwFlags',W.DWORD),('wShowWindow',W.WORD),
              ('cbReserved2',W.WORD),('lpReserved2',C.c_void_p),('hStdInput',W.HANDLE),('hStdOutput',W.HANDLE),('hStdError',W.HANDLE)]
class StartupEx(C.Structure):_fields_=[('StartupInfo',Startup),('lpAttributeList',C.c_void_p)]
class Process(C.Structure):_fields_=[('hProcess',W.HANDLE),('hThread',W.HANDLE),('dwProcessId',W.DWORD),('dwThreadId',W.DWORD)]
class Capabilities(C.Structure):_fields_=[('sid',C.c_void_p),('capabilities',C.c_void_p),('count',W.DWORD),('reserved',W.DWORD)]
class BasicLimit(C.Structure):
    _fields_=[('processTime',C.c_int64),('jobTime',C.c_int64),('flags',W.DWORD),('minWS',C.c_size_t),('maxWS',C.c_size_t),
              ('active',W.DWORD),('affinity',C.c_size_t),('priority',W.DWORD),('scheduling',W.DWORD)]
class IOCounters(C.Structure):_fields_=[(n,C.c_uint64) for n in ('readOps','writeOps','otherOps','readBytes','writeBytes','otherBytes')]
class JobLimit(C.Structure):
    _fields_=[('basic',BasicLimit),('io',IOCounters),('processMemory',C.c_size_t),('jobMemory',C.c_size_t),
              ('peakProcessMemory',C.c_size_t),('peakJobMemory',C.c_size_t)]

def libraries():
    kernel=C.WinDLL('kernel32',use_last_error=True);user=C.WinDLL('userenv',use_last_error=True);adv=C.WinDLL('advapi32',use_last_error=True)
    signatures={
      'CreatePipe':([C.POINTER(W.HANDLE),C.POINTER(W.HANDLE),C.POINTER(SecurityAttributes),W.DWORD],W.BOOL),
      'SetHandleInformation':([W.HANDLE,W.DWORD,W.DWORD],W.BOOL),
      'CreateFileW':([W.LPCWSTR,W.DWORD,W.DWORD,C.POINTER(SecurityAttributes),W.DWORD,W.DWORD,W.HANDLE],W.HANDLE),
      'CloseHandle':([W.HANDLE],W.BOOL),'CreateJobObjectW':([C.c_void_p,W.LPCWSTR],W.HANDLE),
      'SetInformationJobObject':([W.HANDLE,C.c_int,C.c_void_p,W.DWORD],W.BOOL),
      'AssignProcessToJobObject':([W.HANDLE,W.HANDLE],W.BOOL),
      'InitializeProcThreadAttributeList':([C.c_void_p,W.DWORD,W.DWORD,C.POINTER(C.c_size_t)],W.BOOL),
      'UpdateProcThreadAttribute':([C.c_void_p,W.DWORD,C.c_size_t,C.c_void_p,C.c_size_t,C.c_void_p,C.c_void_p],W.BOOL),
      'DeleteProcThreadAttributeList':([C.c_void_p],None),
      'CreateProcessW':([W.LPCWSTR,W.LPWSTR,C.c_void_p,C.c_void_p,W.BOOL,W.DWORD,C.c_void_p,W.LPCWSTR,C.POINTER(StartupEx),C.POINTER(Process)],W.BOOL),
      'ResumeThread':([W.HANDLE],W.DWORD),'WaitForSingleObject':([W.HANDLE,W.DWORD],W.DWORD),
      'GetExitCodeProcess':([W.HANDLE,C.POINTER(W.DWORD)],W.BOOL),
      'TerminateJobObject':([W.HANDLE,W.UINT],W.BOOL),
      'ReadFile':([W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p],W.BOOL),
      'WriteFile':([W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p],W.BOOL),
      'LocalFree':([C.c_void_p],C.c_void_p),
    }
    for name,(args,result) in signatures.items():
        fn=getattr(kernel,name);fn.argtypes=args;fn.restype=result
    user.CreateAppContainerProfile.argtypes=[W.LPCWSTR,W.LPCWSTR,W.LPCWSTR,C.c_void_p,W.DWORD,C.POINTER(C.c_void_p)]
    user.CreateAppContainerProfile.restype=C.c_long
    user.DeriveAppContainerSidFromAppContainerName.argtypes=[W.LPCWSTR,C.POINTER(C.c_void_p)];user.DeriveAppContainerSidFromAppContainerName.restype=C.c_long
    user.GetAppContainerFolderPath.argtypes=[W.LPCWSTR,C.POINTER(W.LPWSTR)];user.GetAppContainerFolderPath.restype=C.c_long
    adv.ConvertSidToStringSidW.argtypes=[C.c_void_p,C.POINTER(W.LPWSTR)];adv.ConvertSidToStringSidW.restype=W.BOOL
    return kernel,user,adv

def check(result):
    if not result:raise C.WinError(C.get_last_error())
    return result

@lru_cache(maxsize=2)
def profile(executable):
    kernel,user,adv=libraries();sid=C.c_void_p()
    result=user.CreateAppContainerProfile('MehrChat.MediaPreview.v1','MehrChat media preview','Isolated media decoding',None,0,C.byref(sid))
    if result<0 and user.DeriveAppContainerSidFromAppContainerName('MehrChat.MediaPreview.v1',C.byref(sid))<0:raise OSError('AppContainer unavailable')
    sid_string=W.LPWSTR();check(adv.ConvertSidToStringSidW(sid,C.byref(sid_string)))
    sid_text=sid_string.value;kernel.LocalFree(C.cast(sid_string,C.c_void_p))
    folder=W.LPWSTR()
    if user.GetAppContainerFolderPath(sid_text,C.byref(folder))<0:raise OSError('Private preview directory unavailable')
    temp=Path(folder.value)/'Temp';temp.mkdir(parents=True,exist_ok=True)
    # Both ACL changes are confined to this binary and this dedicated sandbox.
    system=Path(os.environ['SystemRoot'])/'System32'
    for target,permission in [(executable,'(RX)'),(str(temp),'(OI)(CI)F')]:
        subprocess.run([str(system/'icacls.exe'),target,'/grant','*'+sid_text+':'+permission],
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,creationflags=0x08000000)
    return sid,str(temp)

def run_isolated(executable,raw,timeout=15):
    kernel,_,_=libraries();sid,temp=profile(str(executable.resolve()))
    caps=Capabilities(sid,None,0,0);sa=SecurityAttributes(C.sizeof(SecurityAttributes),None,True)
    input_read,input_write,output_read,output_write=(W.HANDLE() for _ in range(4))
    handles=[];process=Process();attributes=None;job=None
    result=bytearray();errors=[]
    try:
        check(kernel.CreatePipe(C.byref(input_read),C.byref(input_write),C.byref(sa),0));handles.extend([input_read,input_write])
        check(kernel.CreatePipe(C.byref(output_read),C.byref(output_write),C.byref(sa),0));handles.extend([output_read,output_write])
        check(kernel.SetHandleInformation(input_write,1,0));check(kernel.SetHandleInformation(output_read,1,0))
        null=kernel.CreateFileW('NUL',0x40000000,3,C.byref(sa),3,0,None)
        if null in (None,C.c_void_p(-1).value):raise C.WinError(C.get_last_error())
        handles.append(null)
        size=C.c_size_t();kernel.InitializeProcThreadAttributeList(None,2,0,C.byref(size))
        attributes=C.create_string_buffer(size.value);check(kernel.InitializeProcThreadAttributeList(attributes,2,0,C.byref(size)))
        check(kernel.UpdateProcThreadAttribute(attributes,0,0x20009,C.byref(caps),C.sizeof(caps),None,None))
        inherited=(W.HANDLE*3)(input_read.value,output_write.value,null)
        check(kernel.UpdateProcThreadAttribute(attributes,0,0x20002,inherited,C.sizeof(inherited),None,None))
        startup=StartupEx();startup.StartupInfo.cb=C.sizeof(startup);startup.lpAttributeList=C.cast(attributes,C.c_void_p)
        startup.StartupInfo.dwFlags=0x100;startup.StartupInfo.hStdInput=input_read;startup.StartupInfo.hStdOutput=output_write;startup.StartupInfo.hStdError=null
        env={'SystemRoot':os.environ['SystemRoot'],'WINDIR':os.environ.get('WINDIR',os.environ['SystemRoot']),
             'TEMP':temp,'TMP':temp,'PYINSTALLER_RESET_ENVIRONMENT':'1'}
        environment=C.create_unicode_buffer('\0'.join(k+'='+v for k,v in sorted(env.items()))+'\0\0')
        command=C.create_unicode_buffer(subprocess.list2cmdline([str(executable)]))
        check(kernel.CreateProcessW(str(executable),command,None,None,True,0x00080000|0x400|4|0x08000000,
                                    environment,temp,C.byref(startup),C.byref(process)))
        job=check(kernel.CreateJobObjectW(None,None));limits=JobLimit()
        limits.basic.flags=0x2000|0x100|0x200|0x8|0x4;limits.basic.jobTime=10*10_000_000;limits.basic.active=4
        limits.processMemory=512*1024*1024;limits.jobMemory=768*1024*1024
        check(kernel.SetInformationJobObject(job,9,C.byref(limits),C.sizeof(limits)))
        check(kernel.AssignProcessToJobObject(job,process.hProcess))
        # Close our copies of child pipe endpoints; inherited handles remain valid.
        for handle in (input_read,output_write,null):kernel.CloseHandle(handle);handles.remove(handle)
        def write():
            try:
                offset=0
                while offset<len(raw):
                    block=raw[offset:offset+65536];buffer=C.create_string_buffer(block);count=W.DWORD()
                    check(kernel.WriteFile(input_write,buffer,len(block),C.byref(count),None));offset+=count.value
            except OSError:errors.append('input')
            finally:kernel.CloseHandle(input_write)
        def read():
            buffer=C.create_string_buffer(65536);count=W.DWORD()
            while kernel.ReadFile(output_read,buffer,len(buffer),C.byref(count),None) and count.value:
                result.extend(buffer.raw[:count.value])
                if len(result)>272048:
                    errors.append('output');kernel.TerminateJobObject(job,2);break
        writer=threading.Thread(target=write,daemon=True);reader=threading.Thread(target=read,daemon=True)
        writer.start();reader.start();kernel.ResumeThread(process.hThread)
        status=kernel.WaitForSingleObject(process.hProcess,int(timeout*1000))
        if status!=0:raise OSError('Preview timeout')
        code=W.DWORD();check(kernel.GetExitCodeProcess(process.hProcess,C.byref(code)))
        reader.join(1);writer.join(1)
        if code.value or errors or reader.is_alive():raise OSError('Preview worker rejected media')
        return bytes(result)
    finally:
        if job:kernel.CloseHandle(job)
        for handle in handles:
            if handle is not input_write:kernel.CloseHandle(handle)
        for handle in (process.hThread,process.hProcess):
            if handle:kernel.CloseHandle(handle)
        if attributes is not None:kernel.DeleteProcThreadAttributeList(attributes)
