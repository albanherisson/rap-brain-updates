-- Correctif du pont de démarrage distant pour Rap Brain.
-- Exécuter cette activation une fois sur le Mac où la première activation a réussi.

set repositoryRoot to "https://raw.githubusercontent.com/albanherisson/rap-brain-updates/ba41fede47126efe8527d4e076f88d2784bd65c2/"
set setupFiles to {{"remote-development/mac_install_agent.py", "e4af248672cba48907401747383bf857112554591235165cf93616ff46d294e8"}, {"remote-development/ollama-reusable/mac_activate_manager_start.py", "e31fb2d2ced9c0b35b200688193d175f366fba669853e57d8a8c107376940a49"}, {"remote-development/ollama-reusable/mac_manager_start_request.py", "89ed14eb8f72ec6e32f94b082dfd9f7a8a80ecd100dafcef7e653a3d05bef6a4"}, {"remote-development/signed-restart/mac_manager_install_request.py", "4db7de0efb15f7cae34d6312ac00688e0caa7358661529115ccb50c50279c2bf"}}
set agentPlist to (POSIX path of (path to home folder)) & "Library/LaunchAgents/com.gns.rapbrain.remote.p0.plist"
set workingFolder to do shell script "/usr/bin/mktemp -d -t rapbrain-remote-start"

try
	set pythonPath to do shell script "/usr/libexec/PlistBuddy -c " & quoted form of "Print :ProgramArguments:0" & " " & quoted form of agentPlist
	if pythonPath does not start with "/" then error "Le Python configuré pour Rap Brain est introuvable."
	set changeFolder to "cd " & quoted form of workingFolder & " && "
	repeat with setupFile in setupFiles
		set repositoryPath to item 1 of setupFile
		set expectedHash to item 2 of setupFile
		set localName to do shell script "/usr/bin/basename " & quoted form of repositoryPath
		set downloadCommand to "/usr/bin/curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --connect-timeout 10 --max-time 40 --output " & quoted form of localName & " " & quoted form of (repositoryRoot & repositoryPath)
		do shell script changeFolder & downloadCommand
		do shell script changeFolder & "/usr/bin/printf '%s\\n' " & quoted form of (expectedHash & "  " & localName) & " | /usr/bin/shasum -a 256 -c -"
	end repeat
	set activationMessage to do shell script changeFolder & quoted form of pythonPath & " -I -B mac_activate_manager_start.py"
	do shell script "/bin/rm -rf " & quoted form of workingFolder
	display dialog activationMessage with title "Rap Brain" buttons {"OK"} default button "OK"
on error errorMessage number errorNumber
	try
		do shell script "/bin/rm -rf " & quoted form of workingFolder
	end try
	if errorNumber is not -128 then display dialog ("Activation impossible." & return & errorMessage) with title "Rap Brain" buttons {"OK"} default button "OK"
end try
