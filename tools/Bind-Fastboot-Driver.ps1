param(
 [Parameter(Mandatory=$true)][string]$InstanceId,
 [Parameter(Mandatory=$true)][string]$InfPath,
 [switch]$Install
)
$ErrorActionPreference = 'Stop'
$taskDeviceId = $InstanceId
$taskInfPath = (Resolve-Path -LiteralPath $InfPath -ErrorAction Stop).Path
$taskDevice = Get-PnpDevice -PresentOnly -InstanceId $taskDeviceId
$taskIds = (Get-PnpDeviceProperty -InstanceId $taskDeviceId -KeyName 'DEVPKEY_Device_HardwareIds').Data
if ($taskIds -notcontains 'USB\VID_18D1&PID_D00D') { throw '目标硬件 ID 不符。' }
$taskSignature = Get-AuthenticodeSignature -LiteralPath (Join-Path (Split-Path $taskInfPath) 'androidwinusba64.cat')
if ($taskSignature.Status -ne 'Valid' -or $taskSignature.SignerCertificate.Subject -notmatch 'Google LLC') { throw 'Google 驱动目录签名验证失败。' }
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class ScopedFastbootDriver {
 [StructLayout(LayoutKind.Sequential)] public struct DEV {
  public uint cbSize; public Guid ClassGuid; public uint DevInst; public IntPtr Reserved;
 }
 [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public struct PARAM {
  public uint cbSize, Flags, FlagsEx; public IntPtr hwndParent, InstallMsgHandler, InstallMsgHandlerContext, FileQueue, ClassInstallReserved;
  public uint Reserved; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=260)] public string DriverPath;
 }
 [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public struct DRIVER {
  public uint cbSize, DriverType; public IntPtr Reserved;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=256)] public string Description;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=256)] public string MfgName;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst=256)] public string ProviderName;
  public System.Runtime.InteropServices.ComTypes.FILETIME DriverDate; public ulong DriverVersion;
 }
 [DllImport("setupapi.dll", SetLastError=true)] static extern IntPtr SetupDiCreateDeviceInfoList(IntPtr guid, IntPtr hwnd);
 [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiOpenDeviceInfoW(IntPtr set, string id, IntPtr hwnd, uint flags, ref DEV dev);
 [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiGetDeviceInstallParamsW(IntPtr set, ref DEV dev, ref PARAM param);
 [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiSetDeviceInstallParamsW(IntPtr set, ref DEV dev, ref PARAM param);
 [DllImport("setupapi.dll", SetLastError=true)] static extern bool SetupDiBuildDriverInfoList(IntPtr set, ref DEV dev, uint type);
 [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool SetupDiEnumDriverInfoW(IntPtr set, ref DEV dev, uint type, uint index, ref DRIVER driver);
 [DllImport("setupapi.dll", SetLastError=true)] static extern bool SetupDiDestroyDriverInfoList(IntPtr set, ref DEV dev, uint type);
 [DllImport("setupapi.dll", SetLastError=true)] static extern bool SetupDiDestroyDeviceInfoList(IntPtr set);
 [DllImport("newdev.dll", SetLastError=true)] static extern bool DiInstallDevice(IntPtr hwnd, IntPtr set, ref DEV dev, ref DRIVER driver, uint flags, out bool reboot);
 static void Check(bool ok, string stage) { if(!ok) throw new Win32Exception(Marshal.GetLastWin32Error(), stage); }
 public static string Run(string id, string inf, bool install) {
  IntPtr set=SetupDiCreateDeviceInfoList(IntPtr.Zero,IntPtr.Zero);
  if(set==new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());
  DEV dev=new DEV();dev.cbSize=(uint)Marshal.SizeOf(typeof(DEV)); bool built=false;
  try {
   Check(SetupDiOpenDeviceInfoW(set,id,IntPtr.Zero,0,ref dev),"Open target device");
   PARAM p=new PARAM();p.cbSize=(uint)Marshal.SizeOf(typeof(PARAM));
   Check(SetupDiGetDeviceInstallParamsW(set,ref dev,ref p),"Read install parameters");
   p.Flags|=0x00010000; // DI_ENUMSINGLEINF: only enumerate this signed INF.
   p.FlagsEx|=0x00000800; // DI_FLAGSEX_ALLOWEXCLUDEDDRVS
   p.DriverPath=inf;
   Check(SetupDiSetDeviceInstallParamsW(set,ref dev,ref p),"Select signed INF");
   Check(SetupDiBuildDriverInfoList(set,ref dev,1),"Build class driver models");built=true;
   string listing=""; DRIVER selected=new DRIVER();bool found=false;
   for(uint i=0;;i++) {
    DRIVER d=new DRIVER();d.cbSize=(uint)Marshal.SizeOf(typeof(DRIVER));
    if(!SetupDiEnumDriverInfoW(set,ref dev,1,i,ref d)) {
     int error=Marshal.GetLastWin32Error();if(error==259) break;throw new Win32Exception(error,"Enumerate driver models");
    }
    listing+=d.Description+" | "+d.ProviderName+"\n";
    if(!found && d.Description=="Android Bootloader Interface" && d.ProviderName.Contains("Google")) { selected=d;found=true; }
   }
   if(!found) throw new Exception("Signed Android Bootloader Interface model not found.");
   if(!install) return listing+"MODEL_READY; device binding not changed.";
   bool reboot;Check(DiInstallDevice(IntPtr.Zero,set,ref dev,ref selected,0,out reboot),"Install selected signed model on target device");
   return "Installed Android Bootloader Interface on "+id+"; WindowsRestartRequired="+reboot;
  } finally { if(built) SetupDiDestroyDriverInfoList(set,ref dev,1);SetupDiDestroyDeviceInfoList(set); }
 }
}
'@
[ScopedFastbootDriver]::Run($taskDeviceId, $taskInfPath, [bool]$Install)
