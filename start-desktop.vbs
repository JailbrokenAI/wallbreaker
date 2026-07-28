Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
' /k keeps console open so user can see errors
sh.Run "cmd.exe /k cd /d """ & dir & """ && call start-desktop.bat", 1, False
