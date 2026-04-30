@echo off
set CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
  echo ERROR=CSC_NOT_FOUND
  exit /b 1
)
"%CSC%" /target:exe /out:OR2103Bridge.exe /reference:OR2127LIB.dll OR2103Bridge.cs
