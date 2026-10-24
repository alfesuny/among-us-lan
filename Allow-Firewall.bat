@echo off
rem Lets other PCs on your network reach the game when YOU host.
rem Run this on the hosting PC if friends can't see or join your game.
rem It asks for administrator rights, then:
rem   1. removes "block" rules Windows created for Python if someone clicked Cancel on the firewall popup
rem   2. allows the game ports: TCP 4321 (game) and UDP 4320 (LAN game list)
net session >nul 2>&1
if errorlevel 1 (
    echo Asking for administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$blocks = Get-NetFirewallApplicationFilter | Where-Object { $_.Program -like '*python*' } | Get-NetFirewallRule | Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' };" ^
  "if ($blocks) { $blocks | ForEach-Object { Write-Host ('Removing block rule: ' + $_.DisplayName) }; $blocks | Remove-NetFirewallRule };" ^
  "Get-NetFirewallRule -DisplayName 'Among Us LAN*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule;" ^
  "New-NetFirewallRule -DisplayName 'Among Us LAN (game TCP 4321)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 4321 -Profile Any | Out-Null;" ^
  "New-NetFirewallRule -DisplayName 'Among Us LAN (game list UDP 4320)' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 4320 -Profile Any | Out-Null;" ^
  "Write-Host 'Firewall rules added. Friends on your network can now join.'"
pause
