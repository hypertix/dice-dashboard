' DICE 벤치 대시보드 — 창 없이 실행 (소스/개발 PC 용)
' 더블클릭하면: 콘솔 창 없이 서버가 뜨고 브라우저가 자동으로 열린다.
' 마지막 대시보드 탭을 닫으면 서버도 몇 초 뒤 자동 종료된다.
' 콘솔 로그가 필요하면 run.bat 을 사용할 것 (창 표시, 자동 종료 없음).
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "pythonw -m server.app", 0, False
