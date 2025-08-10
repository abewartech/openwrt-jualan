
$process = Start-Process -FilePath "telnet" -ArgumentList "192.168.31.1" -PassThru -NoNewWindow
Start-Sleep -Seconds 3
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("root")
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
