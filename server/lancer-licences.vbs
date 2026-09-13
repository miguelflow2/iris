' Lanceur discret du serveur de licences VELA (port 8110, sans fenêtre).
Dim sh
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\migue\Downloads\startup\iris\server"
sh.Run """C:\Users\migue\Downloads\startup\iris\server\.venv\Scripts\python.exe"" -m licences --port 8110", 0, False
