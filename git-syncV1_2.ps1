<#
.SYNOPSIS
    Git Commit and Sync Script with GitHub Integration
.DESCRIPTION
    A robust PowerShell script for managing Git workflows with GitHub integration.
    
    Key Features:
    - Automatic branch detection and synchronization
    - Seamless GitHub authentication using GitHub CLI
    - Comprehensive commit message generation with change details
    - Conflict detection and resolution assistance
    - Secure credential handling with GitHub CLI
    - Detailed logging with timestamps
    - Automatic repository initialization and remote setup
    - Verification of sync status after push operations
    
    The script prioritizes security by using GitHub CLI for authentication,
    avoiding the need to store credentials in plaintext. It provides clear
    feedback at each step and handles errors gracefully.
    
    Prerequisites:
    - Git (https://git-scm.com/)
    - GitHub CLI (https://cli.github.com/)
    - GitHub CLI authentication (run 'gh auth login' if not already authenticated)
#>

#Requires -Version 5.1

# Configuration
$Script:LogFile = Join-Path $PSScriptRoot "git_sync_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
$Script:MaxRetries = 3
$Script:RetryDelay = 5 # seconds

# ANSI color codes for better console output
$Script:Colors = @{
    Success = "Green"
    Error = "Red"
    Warning = "Yellow"
    Info = "Cyan"
    Debug = "Gray"
}

function Write-Log {
    param(
        [string]$Message,
        [ValidateSet("Success", "Error", "Warning", "Info", "Debug")]
        [string]$Level = "Info"
    )
    
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"
    $color = $Script:Colors[$Level]
    
    # Write to console with color
    Write-Host $logMessage -ForegroundColor $color
    
    # Write to log file
    Add-Content -Path $Script:LogFile -Value $logMessage -ErrorAction SilentlyContinue
}

function Test-GitInstallation {
    try {
        $gitVersion = git --version
        return $true
    } catch {
        Write-Log "Git is not installed or not in PATH" "Error"
        return $false
    }
}

function Test-GitRepository {
    try {
        $gitDir = git rev-parse --git-dir 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Not a Git repository. Initializing new repository..." "Info"
            git init | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Failed to initialize Git repository" }
            return $true
        }
        
        # Check if there are any commits
        $hasCommits = git rev-parse --verify HEAD 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Log "No commits in repository. Will guide through initial commit." "Info"
            return $true
        }
        
        return $true
    } catch {
        Write-Log "Error checking Git repository: $_" "Error"
        return $false
    }
}

function Test-GitRemote {
    try {
        $remotes = git remote -v
        return $remotes -ne $null -and $remotes.Count -gt 0
    } catch {
        Write-Log "Error checking Git remotes: $_" "Error"
        return $false
    }
}

function Test-GitHubCli {
    try {
        $ghVersion = gh --version 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        
        # Check if authenticated with write access
        $authStatus = gh auth status 2>&1
        return $authStatus -match "Logged in to github.com" -and $authStatus -match "Token scopes:.*(repo|delete_repo|workflow|write:packages|delete:packages|admin:org|admin:public_key|admin:repo_hook|admin:org_hook|gist|notifications|user|delete_repo|admin:gpg_key)"
    } catch {
        return $false
    }
}

function Initialize-GitHubAuth {
    try {
        if (Test-GitHubCli) { return $true }
        
        Write-Log "GitHub CLI is not authenticated or doesn't have write access. Let's set it up..." "Warning"
        $authChoice = Read-Host "Choose authentication method:`n1. Login with GitHub CLI (recommended)`n2. Use SSH key`n3. Use Personal Access Token (PAT)`nEnter your choice (1-3):"
        
        switch ($authChoice) {
            '1' {
                gh auth login --hostname github.com
                return $LASTEXITCODE -eq 0
            }
            '2' {
                # Return true to use SSH URL
                return $true
            }
            '3' {
                $token = Read-Host "Enter your GitHub Personal Access Token (with 'repo' scope):"
                if (-not $token) { return $false }
                
                $env:GH_TOKEN = $token
                return $true
            }
            default {
                Write-Log "Invalid choice. Please try again." "Error"
                return $false
            }
        }
    } catch {
        Write-Log "Error during GitHub authentication: $_" "Error"
        return $false
    }
}

function New-GitHubRepository {
    param(
        [string]$Name,
        [string]$Description = "",
        [bool]$IsPrivate = $false,
        [string]$AccessToken = $null
    )
    
    try {
        $visibility = if ($IsPrivate) { "private" } else { "public" }
        $repoUrl = $null
        
        if (Test-GitHubCli) {
            # Use GitHub CLI if available
            $createArgs = @("repo", "create", $Name, "--$visibility", "--source=.")
            if ($Description) { $createArgs += "--description", $Description }
            
            $output = & gh $createArgs 2>&1 | Out-String
            
            if ($LASTEXITCODE -eq 0) {
                $username = gh api user --jq '.login' | ForEach-Object { $_.Trim() }
                $repoUrl = "https://github.com/$username/$Name.git"
                Write-Log "Repository created successfully using GitHub CLI" "Success"
                return $repoUrl
            } else {
                throw "Failed to create repository: $output"
            }
        } else {
            # Fall back to direct API
            if (-not $AccessToken) {
                $AccessToken = Read-Host "GitHub Personal Access Token (with 'repo' scope) is required. Enter token:"
                if (-not $AccessToken) { throw "GitHub token is required" }
            }
            
            $headers = @{
                "Authorization" = "token $AccessToken"
                "Accept" = "application/vnd.github.v3+json"
            }
            
            $body = @{
                name = $Name
                description = $Description
                private = $IsPrivate
                auto_init = $false
            } | ConvertTo-Json
            
            $response = Invoke-RestMethod -Uri "https://api.github.com/user/repos" -Method Post -Headers $headers -Body $body
            $repoUrl = $response.clone_url
            Write-Log "Repository created successfully using GitHub API" "Success"
        }
        
        return $repoUrl
    } catch {
        Write-Log "Failed to create GitHub repository: $_" "Error"
        return $null
    }
}

function ConvertTo-SshUrl {
    param([string]$HttpsUrl)
    if ($HttpsUrl -match '^https://github\.com/([^/]+)/([^/]+?)(\.git)?$') {
        return "git@github.com:$($matches[1])/$($matches[2]).git"
    }
    return $null
}

function Initialize-GitRepository {
    param(
        [string]$RemoteUrl = $null,
        [string]$RepositoryName = (Split-Path -Leaf $PWD)
    )
    
    try {
        # Check if we need to make a commit
        $status = git status --porcelain
        if ($status) {
            Write-Log "Staging all changes for commit..." "Info"
            git add .
            
            # Generate descriptive commit message based on changed files
            $changedFiles = git diff --name-only --cached
            $fileArray = $changedFiles -split "`n" | Where-Object { $_ -ne "" }
            
            # Check if this is the first commit
            $isInitialCommit = -not (git rev-parse --verify HEAD 2>$null)
            if ($isInitialCommit) {
                $commitMessage = "Initial commit: Add project files"
                Write-Log "Creating initial commit..." "Info"
            } else {
                # Create descriptive message for automated commits
                $displayCount = [Math]::Min(3, $fileArray.Count)
                $fileList = $fileArray | Select-Object -First $displayCount
                $commitMessage = "chore: update " + ($fileList -join ", ")
                
                if ($fileArray.Count -gt $displayCount) {
                    $commitMessage += " (+$($fileArray.Count - $displayCount) more)"
                }
                Write-Log "Creating commit..." "Info"
            }
            git commit -m $commitMessage
            
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to create initial commit"
            }
            Write-Log "Initial commit created successfully" "Success"
        }
        
        # Check if we need to set up remote
        if ($RemoteUrl) {
            # Remove existing remote if it exists
            if (Test-GitRemote) {
                $currentUrl = (git remote get-url origin).Trim()
                
                # If URL is different, update it
                if ($currentUrl -ne $RemoteUrl -and $currentUrl -ne (ConvertTo-SshUrl $RemoteUrl)) {
                    Write-Log "Updating remote URL from $currentUrl to $RemoteUrl" "Info"
                    git remote set-url origin $RemoteUrl
                }
            } else {
                # Add new remote
                Write-Log "Adding remote repository: $RemoteUrl" "Info"
                git remote add origin $RemoteUrl
            }
            
            # Convert to SSH URL if using SSH
            $pushUrl = $RemoteUrl
            if ($RemoteUrl -match '^https://github\.com/') {
                $sshUrl = ConvertTo-SshUrl $RemoteUrl
                $useSsh = (Read-Host "Use SSH for pushing? (y/n, recommended for better security)").ToLower() -eq 'y'
                if ($useSsh) { 
                    $pushUrl = $sshUrl
                    git remote set-url origin $pushUrl
                    Write-Log "Updated remote to use SSH URL: $pushUrl" "Info"
                }
            }
            
            # Set upstream branch
            $defaultBranch = git symbolic-ref --short HEAD
            if (-not $defaultBranch) { $defaultBranch = "main" }
            
            # Configure GitHub CLI to use SSH if available
            if (Test-GitHubCli) {
                gh config set git_protocol ssh --host github.com
            }
            
            # Check if this is the first push
            $isInitialPush = -not (git ls-remote --heads origin $defaultBranch 2>$null)
            if ($isInitialPush) {
                Write-Log "Pushing initial commit to remote..." "Info"
            } else {
                Write-Log "Pushing changes to remote..." "Info"
            }
            $pushOutput = git push origin $defaultBranch 2>&1 | Out-String
            
            if ($LASTEXITCODE -eq 0) {
                $commitHash = git rev-parse --short HEAD
                Write-Log "✓ Successfully pushed commit $commitHash to remote." "Success"
                
                # Verify sync status
                git fetch origin
                $localCommit = git rev-parse $defaultBranch
                $remoteCommit = git rev-parse "origin/$defaultBranch" 2>$null
                
                if ($LASTEXITCODE -eq 0) {
                    if ($localCommit -eq $remoteCommit) {
                        Write-Log "✓ Repository is now in sync with remote." "Success"
                    } else {
                        Write-Log "! Warning: Local and remote branches have diverged. Consider pulling remote changes." "Warning"
                    }
                } else {
                    Write-Log "! Could not verify remote branch. Make sure the remote branch exists and you have proper permissions." "Warning"
                }
            } else {
                Write-Log "! Push failed. Output: $pushOutput" "Error"
                throw "Failed to push changes to remote"
            }
        }
        
        return $true
    } catch {
        Write-Log "Error initializing repository: $_" "Error"
        return $false
    }
}

function Get-GitStatus {
    try {
        $status = git status --porcelain
        if ($LASTEXITCODE -ne 0) { throw "Git status failed" }
        return $status
    } catch {
        Write-Log "Failed to get git status: $_" "Error"
        throw
    }
}

function Invoke-GitPull {
    param(
        [string]$Remote = "origin",
        [string]$Branch
    )
    
    $attempt = 1
    while ($attempt -le $Script:MaxRetries) {
        try {
            Write-Log "Pulling changes from $Remote/$Branch (Attempt $attempt/$Script:MaxRetries)..." "Info"
            $pullOutput = git pull $Remote $Branch --rebase 2>&1 | Out-String
            
            if ($LASTEXITCODE -eq 0) {
                Write-Log "Successfully pulled changes from $Remote/$Branch" "Success"
                return $true
            }
            
            if ($pullOutput -match "CONFLICT") {
                Write-Log "Merge conflict detected. Please resolve conflicts and run the script again." "Error"
                Write-Log "Conflict details: $pullOutput" "Debug"
                exit 1
            }
            
            throw $pullOutput
        } catch {
            if ($attempt -eq $Script:MaxRetries) {
                Write-Log "Failed to pull after $Script:MaxRetries attempts: $_" "Error"
                return $false
            }
            
            Write-Log "Pull attempt $attempt failed. Retrying in $Script:RetryDelay seconds..." "Warning"
            Start-Sleep -Seconds $Script:RetryDelay
            $attempt++
        }
    }
}

function New-GitCommit {
    param(
        [string]$Message
    )
    
    try {
        # Stage all changes
        git add .
        
        # Create commit
        git commit -m $Message
        
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Successfully created commit with message: $Message" "Success"
            return $true
        }
        
        throw "Git commit failed"
    } catch {
        Write-Log "Failed to create commit: $_" "Error"
        return $false
    }
}

function Invoke-GitPush {
    param(
        [string]$Remote = "origin",
        [string]$Branch
    )
    
    $attempt = 1
    while ($attempt -le $Script:MaxRetries) {
        try {
            Write-Log "Pushing changes to $Remote/$Branch (Attempt $attempt/$Script:MaxRetries)..." "Info"
            git push $Remote $Branch 2>&1 | Out-Null
            
            if ($LASTEXITCODE -eq 0) {
                Write-Log "Successfully pushed changes to $Remote/$Branch" "Success"
                return $true
            }
            
            throw "Git push failed"
        } catch {
            if ($attempt -eq $Script:MaxRetries) {
                Write-Log "Failed to push after $Script:MaxRetries attempts: $_" "Error"
                return $false
            }
            
            Write-Log "Push attempt $attempt failed. Retrying in $Script:RetryDelay seconds..." "Warning"
            Start-Sleep -Seconds $Script:RetryDelay
            $attempt++
        }
    }
}

function Get-GitBranchInfo {
    try {
        $currentBranch = git rev-parse --abbrev-ref HEAD
        $commitHash = git rev-parse --short HEAD
        $remoteUrl = git config --get remote.origin.url
        
        return @{
            Branch = $currentBranch
            CommitHash = $commitHash
            RemoteUrl = $remoteUrl
            Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        }
    } catch {
        Write-Log "Failed to get git branch info: $_" "Error"
        throw
    }
}

function New-CommitMessage {
    $branchInfo = Get-GitBranchInfo
    $changedFiles = git diff --name-only --cached
    
    # Generate a descriptive summary based on changed files
    if (-not $changedFiles) {
        $summary = "chore: sync repository"
    } else {
        $fileArray = $changedFiles -split "`n" | Where-Object { $_ -ne "" }
        $displayCount = [Math]::Min(3, $fileArray.Count)
        $fileList = $fileArray | Select-Object -First $displayCount
        
        # Create a concise summary
        $summary = "chore: update " + ($fileList -join ", ")
        
        if ($fileArray.Count -gt $displayCount) {
            $summary += " (+$($fileArray.Count - $displayCount) more)"
        }
    }
    
    $message = @"
$summary

[$(Get-Date -Format "yyyy-MM-dd HH:mm")] Automated Commit

Branch: $($branchInfo.Branch)
Commit: $($branchInfo.CommitHash)
Remote: $($branchInfo.RemoteUrl)

Changes:
$($changedFiles -join "`n")

# Please enter a description for your changes above this line.
# Lines starting with '#' will be ignored.
"@

    return $message
}

# Main execution
try {
    # Check if Git is installed
    if (-not (Test-GitInstallation)) {
        Write-Log "Git is required but not found. Please install Git and try again." "Error"
        exit 1
    }

    # Check and initialize Git repository if needed
    if (-not (Test-GitRepository)) {
        Write-Log "Failed to initialize Git repository." "Error"
        exit 1
    }
    
    # Check for remote repository
    $hasRemote = Test-GitRemote
    $remoteUrl = $null
    
    if (-not $hasRemote) {
        Write-Log "No remote repository is configured for this project." "Info"
        $setupRemote = Read-Host "Would you like to create a GitHub repository? (y/n)"
        
        if ($setupRemote -eq 'y') {
            $repoName = Read-Host "Enter repository name (leave empty to use '$((Split-Path -Leaf $PWD).ToLower().Replace(' ', '-'))')"
            if (-not $repoName) { $repoName = (Split-Path -Leaf $PWD).ToLower().Replace(' ', '-') }
            
            $repoDesc = Read-Host "Enter repository description (optional)"
            $isPrivate = (Read-Host "Make repository private? (y/n)").ToLower() -eq 'y'
            
            Write-Log "Creating GitHub repository '$repoName'..." "Info"
            $remoteUrl = New-GitHubRepository -Name $repoName -Description $repoDesc -IsPrivate $isPrivate
            
            if (-not $remoteUrl) {
                $remoteUrl = Read-Host "Failed to create repository automatically. Please enter the repository URL manually (or press Enter to skip)"
                if (-not $remoteUrl) {
                    Write-Log "No remote URL provided. You can add it later with 'git remote add origin <url>'" "Warning"
                }
            }
        } else {
            $manualUrl = Read-Host "Would you like to enter an existing repository URL? (y/n)"
            if ($manualUrl -eq 'y') {
                $remoteUrl = Read-Host "Enter the remote repository URL (e.g., https://github.com/username/repo.git)"
                if (-not $remoteUrl) {
                    Write-Log "No remote URL provided. You can add it later with 'git remote add origin <url>'" "Warning"
                }
            } else {
                Write-Log "You can add a remote repository later with 'git remote add origin <url>'" "Info"
            }
        }
    }
    
    # Initialize repository with initial commit and remote if needed
    if (-not (Initialize-GitRepository -RemoteUrl $remoteUrl)) {
        Write-Log "Failed to initialize repository. Please check the logs and try again." "Error"
        exit 1
    }

    # Get current branch info
    $branchInfo = Get-GitBranchInfo
    $currentBranch = $branchInfo.Branch
    $commitHash = $branchInfo.CommitHash

    Write-Log "Starting Git Sync on branch: $currentBranch (Commit: $commitHash)" "Info"

    # Check for changes
    $changes = Get-GitStatus
    if (-not $changes) {
        Write-Log "No local changes to commit." "Info"
        
        # Check sync status with remote
        if (Test-GitRemote) {
            # First try with regular git fetch
            $fetchOutput = git fetch origin 2>&1
            
            # If that fails, try using GitHub CLI for authentication
            if ($LASTEXITCODE -ne 0) {
                Write-Log "Standard git fetch failed, trying with GitHub CLI authentication..." "Info"
                $fetchOutput = gh auth status 2>&1
                
                if ($LASTEXITCODE -eq 0) {
                    # Use GitHub CLI to get the remote URL with authentication
                    $remoteUrl = git config --get remote.origin.url
                    $fetchOutput = git -c credential.helper= -c credential.helper='!gh auth git-credential' fetch origin 2>&1
                    
                    if ($LASTEXITCODE -ne 0) {
                        Write-Log "! Could not fetch from remote using GitHub CLI. Error: $fetchOutput" "Warning"
                        Write-Log "Please ensure you have the necessary permissions for this repository." "Warning"
                        return
                    }
                } else {
                    Write-Log "! Could not authenticate with GitHub CLI. Please run 'gh auth login' first." "Warning"
                    Write-Log "Error: $fetchOutput" "Warning"
                    return
                }
            }
            
            $localBranch = git rev-parse --abbrev-ref HEAD
            $localCommit = git rev-parse $localBranch
            $remoteCommit = git rev-parse "origin/$localBranch" 2>$null
            
            if ($LASTEXITCODE -eq 0) {
                if ($localCommit -eq $remoteCommit) {
                    Write-Log "✓ Repository is in sync with remote." "Success"
                } else {
                    $ahead = $(git rev-list --count "$remoteCommit..$localCommit" 2>$null)
                    $behind = $(git rev-list --count "$localCommit..$remoteCommit" 2>$null)
                    
                    if ($ahead -gt 0 -and $behind -gt 0) {
                        Write-Log "! Local branch has diverged: $ahead local commit(s) ahead, $behind remote commit(s) behind" "Warning"
                    } elseif ($ahead -gt 0) {
                        Write-Log "→ Ready to push $ahead local commit(s) to remote" "Info"
                        
                        # Automatically push using GitHub CLI authentication
                        $pushOutput = git -c credential.helper= -c credential.helper='!gh auth git-credential' push origin HEAD 2>&1
                        if ($LASTEXITCODE -eq 0) {
                            Write-Log "✓ Successfully pushed $ahead commit(s) to remote" "Success"
                            
                            # Verify sync status after push
                            $verifyFetch = git -c credential.helper= -c credential.helper='!gh auth git-credential' fetch origin 2>&1
                            if ($LASTEXITCODE -eq 0) {
                                $localCommit = git rev-parse HEAD
                                $remoteCommit = git rev-parse "origin/$localBranch" 2>$null
                                
                                if ($LASTEXITCODE -eq 0 -and $localCommit -eq $remoteCommit) {
                                    Write-Log "✓ Verified: Local and remote repositories are in sync" "Success"
                                } else {
                                    Write-Log "! Warning: Could not verify sync status. Local and remote may be out of sync." "Warning"
                                }
                            } else {
                                Write-Log "! Could not verify sync status. Failed to fetch from remote: $verifyFetch" "Warning"
                            }
                        } else {
                            Write-Log "! Failed to push to remote: $pushOutput" "Error"
                        }
                    } elseif ($behind -gt 0) {
                        Write-Log "← $behind new commit(s) available on remote" "Info"
                    }
                }
            } else {
                Write-Log "ℹ Remote branch 'origin/$localBranch' doesn't exist yet. Push to create it." "Info"
            }
            return
        }
    }

    # Pull latest changes
    if (-not (Invoke-GitPull -Branch $currentBranch)) {
        Write-Log "Failed to pull changes. Aborting." "Error"
        exit 1
    }

    # Generate and edit commit message
    $commitMessage = New-CommitMessage
    $tempFile = [System.IO.Path]::GetTempFileName()
    $commitMessage | Out-File -FilePath $tempFile -Encoding utf8

    try {
        # Let user edit the commit message
        $editor = $env:GIT_EDITOR
        if (-not $editor) {
            $editor = "notepad.exe" # Default to Notepad on Windows
        }

        Start-Process -FilePath $editor -ArgumentList $tempFile -Wait

        # Read the edited message
        $finalMessage = Get-Content -Path $tempFile -Raw
        $finalMessage = ($finalMessage -split "#.*\n" | Where-Object { $_ -notmatch "^\s*$" } | Select-Object -First 1).Trim()

        if ([string]::IsNullOrWhiteSpace($finalMessage)) {
            Write-Log "Commit message cannot be empty. Aborting." "Error"
            exit 1
        }

        # Create commit
        if (New-GitCommit -Message $finalMessage) {
            # Push changes
            if (Invoke-GitPush -Branch $currentBranch) {
                Write-Log "Successfully completed Git sync." "Success"
                exit 0
            }
        }

        Write-Log "Git sync completed with errors. Check the log at $($Script:LogFile)" "Error"
        exit 1

    } finally {
        # Clean up
        if (Test-Path $tempFile) {
            Remove-Item $tempFile -Force
        }
    }
} catch {
    Write-Log "An unexpected error occurred: $_" "Error"
    Write-Log "$($_.ScriptStackTrace)" "Debug"
    exit 1
}